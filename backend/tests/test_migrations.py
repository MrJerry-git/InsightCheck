import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from app.models import Base


def run_alembic(database_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_initial_migration_builds_all_tables(tmp_path: Path) -> None:
    database_path = tmp_path / "migration-test.db"
    result = run_alembic(database_path, "upgrade", "head")

    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database_path) as connection:
        actual_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'alembic_version'"
            )
        }
    assert actual_tables == set(Base.metadata.tables)


def test_upgrade_from_existing_database_keeps_legacy_rows(tmp_path: Path) -> None:
    """T02 审核要求：从现有 main 数据库版本升级，不能只验证空库 create_all。

    旧库停在 T01 迁移（``c3d8f0a41b27``）时已有患者、检查与指标数据，
    升级到 head 后这些行必须保持可读，并被回填为 manual/numeric/revision=1。
    """

    database_path = tmp_path / "upgrade-from-main.db"
    baseline = run_alembic(database_path, "upgrade", "c3d8f0a41b27")
    assert baseline.returncode == 0, baseline.stderr

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO patients (id, created_at, anonymous_code, gender)"
            " VALUES ('p-legacy', '2026-01-01 00:00:00', 'P-LEGACY', 'male')"
        )
        connection.execute(
            "INSERT INTO health_checks (id, created_at, patient_id, check_date, is_demo)"
            " VALUES ('c-legacy', '2026-01-01 00:00:00', 'p-legacy', '2026-01-05', 0)"
        )
        connection.execute(
            "INSERT INTO lab_metrics (id, created_at, health_check_id, metric_code,"
            " original_name, canonical_name, original_value, value, original_unit,"
            " status, normalization_status, normalization_version)"
            " VALUES ('m-legacy', '2026-01-01 00:00:00', 'c-legacy', 'ALT', 'ALT',"
            " '丙氨酸氨基转移酶', '88', 88.0, 'U/L', 'high', 'normalized', 'v1')"
        )
        connection.commit()

    upgraded = run_alembic(database_path, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    with sqlite3.connect(database_path) as connection:
        patient = connection.execute(
            "SELECT anonymous_code FROM patients WHERE id = 'p-legacy'"
        ).fetchone()
        check = connection.execute(
            "SELECT source_kind, revision_no, is_demo FROM health_checks WHERE id = 'c-legacy'"
        ).fetchone()
        metric = connection.execute(
            "SELECT metric_code, original_value, value, original_unit, source_kind,"
            " value_type, revision_no FROM lab_metrics WHERE id = 'm-legacy'"
        ).fetchone()
        revisions = connection.execute("SELECT COUNT(*) FROM record_revisions").fetchone()[0]

    assert patient == ("P-LEGACY",)
    assert check == ("manual", 1, 0)
    assert metric == ("ALT", "88", 88.0, "U/L", "manual", "numeric", 1)
    # 迁移只做兼容回填，不虚构历史修订记录。
    assert revisions == 0
