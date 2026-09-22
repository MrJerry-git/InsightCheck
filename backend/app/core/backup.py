"""T11：数据库备份与恢复。

SQLite 使用文件级备份（含完整性校验与摘要清单）；PostgreSQL 需要运维使用
``pg_dump``，本模块明确拒绝而不是假装支持。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class BackupError(Exception):
    """备份/恢复失败；消息可直接展示给运维。"""


@lru_cache(maxsize=1)
def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _ancestors(revision: str) -> set[str] | None:
    """返回该 revision 及其全部祖先；未知 revision 返回 None。"""

    script = _script_directory()
    try:
        current = script.get_revision(revision)
    except Exception:  # 未知标识会抛 CommandError，这里统一视为无法判定
        return None
    if current is None:
        return None
    seen: set[str] = set()
    stack = [current]
    while stack:
        node = stack.pop()
        if node.revision in seen:
            continue
        seen.add(node.revision)
        downs = node.down_revision
        for down in (downs,) if isinstance(downs, str) else (downs or ()):
            try:
                child = script.get_revision(down)
            except Exception:
                return None
            if child is not None:
                stack.append(child)
    return seen


def compare_revisions(current: str | None, archived: str | None) -> str:
    """按 Alembic 版本图比较两个版本，而不是按字符串大小。

    返回 ``same`` / ``archived_older`` / ``archived_newer`` / ``diverged`` / ``unknown``。
    revision 标识不是按时间排序的字符串，字符串比较会把旧备份当成新版本。
    """

    if current is None and archived is None:
        return "same"
    if current is None or archived is None:
        return "unknown"
    if current == archived:
        return "same"
    current_ancestors = _ancestors(current)
    archived_ancestors = _ancestors(archived)
    if current_ancestors is None or archived_ancestors is None:
        return "unknown"
    if archived in current_ancestors:
        # 备份版本是当前版本的祖先：恢复会退回旧库结构，必须显式确认。
        return "archived_older"
    if current in archived_ancestors:
        # 备份版本比当前库更新：允许恢复（升级方向）。
        return "archived_newer"
    return "diverged"


@dataclass(frozen=True)
class BackupResult:
    archive_path: Path
    manifest_path: Path
    database_bytes: int
    sha256: str
    revision: str | None


def sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise BackupError("仅 SQLite 支持内置备份；PostgreSQL 请使用 pg_dump/pg_restore")
    return Path(database_url.replace("sqlite:///", "", 1)).expanduser().resolve()


def current_revision(database: Path) -> str | None:
    if not database.exists():
        return None
    with sqlite3.connect(database) as connection:
        try:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            return None
    return None if row is None else str(row[0])


def integrity_ok(database: Path) -> bool:
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(database_url: str, output_dir: Path, *, stamp: str | None = None) -> BackupResult:
    database = sqlite_path(database_url)
    if not database.exists():
        raise BackupError(f"数据库文件不存在：{database}")
    if not integrity_ok(database):
        raise BackupError("源数据库完整性校验失败，已中止备份")
    timestamp = stamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"xunying-{timestamp}.db"
    # 使用 SQLite 在线备份 API，避免复制到写入中的半成品文件。
    with sqlite3.connect(database) as source, sqlite3.connect(archive) as target:
        source.backup(target)
    checksum = digest_file(archive)
    revision = current_revision(archive)
    manifest = {
        "archive": archive.name,
        "created_at": datetime.now(UTC).isoformat(),
        "sha256": checksum,
        "size_bytes": archive.stat().st_size,
        "alembic_revision": revision,
        "source_database": database.name,
    }
    manifest_path = archive.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return BackupResult(
        archive_path=archive,
        manifest_path=manifest_path,
        database_bytes=archive.stat().st_size,
        sha256=checksum,
        revision=revision,
    )


def restore_backup(
    archive: Path, database_url: str, *, force: bool = False, safety_copy: bool = True
) -> dict:
    """恢复备份：先校验摘要与完整性，再替换目标数据库（默认保留安全副本）。"""

    target = sqlite_path(database_url)
    if not archive.exists():
        raise BackupError(f"备份文件不存在：{archive}")
    manifest_path = archive.with_suffix(".manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("sha256") and manifest["sha256"] != digest_file(archive):
            raise BackupError("备份文件摘要与清单不一致，拒绝恢复")
    if not integrity_ok(archive):
        raise BackupError("备份文件完整性校验失败，拒绝恢复")
    if target.exists() and not force:
        raise BackupError("目标数据库已存在；确认覆盖请显式使用 force")
    archived_revision = current_revision(archive)
    current = current_revision(target) if target.exists() else None
    if target.exists() and current is not None:
        if archived_revision is None:
            raise BackupError("备份未记录 Alembic 版本，无法确认与当前数据库的先后关系")
        relation = compare_revisions(current, archived_revision)
        if relation in {"archived_older", "diverged", "unknown"}:
            reasons = {
                "archived_older": f"备份版本 {archived_revision} 早于当前数据库 {current}",
                "diverged": (
                    f"备份版本 {archived_revision} 与当前数据库 {current} 不在同一条迁移链上"
                ),
                "unknown": (
                    f"无法在迁移图中确认备份版本 {archived_revision} 与当前数据库 "
                    f"{current} 的先后关系"
                ),
            }
            raise BackupError(f"{reasons[relation]}，请先确认迁移策略后再恢复")
    safety_path = None
    if target.exists() and safety_copy:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        safety_path = target.with_suffix(target.suffix + f".pre-restore-{stamp}")
        shutil.copy2(target, safety_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(archive, target)
    return {
        "restored_to": str(target),
        "alembic_revision": archived_revision,
        "safety_copy": None if safety_path is None else str(safety_path),
    }
