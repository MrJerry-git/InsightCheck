"""T11：健康明细、请求日志、生产配置与备份恢复。"""

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.backup import BackupError, create_backup, current_revision, restore_backup
from app.models import Base, HealthCheck, Patient
from app.models.enums import AccountRole, Gender
from app.services.auth_service import AuthService

ADMIN_PASSWORD = "Admin-Pass-2026!"


def make_account(db, username, role=AccountRole.DOCTOR):
    password = ADMIN_PASSWORD if role is AccountRole.ADMIN else "Doctor-Pass-2026!"
    return AuthService(db, iterations=10_000).create_account(
        username=username, password=password, display_name=username, role=role
    )


def login(client, username, role=AccountRole.DOCTOR):
    password = ADMIN_PASSWORD if role is AccountRole.ADMIN else "Doctor-Pass-2026!"
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_health_detail_reports_real_state(test_app, db_session):
    make_account(db_session, "doctor-a")
    make_account(db_session, "admin-a", role=AccountRole.ADMIN)
    patient = Patient(anonymous_code="P-OPS-001", gender=Gender.UNKNOWN)
    db_session.add(patient)
    db_session.commit()

    with TestClient(test_app) as client:
        doctor = login(client, "doctor-a")
        admin = login(client, "admin-a", AccountRole.ADMIN)
        assert client.get("/api/v1/health/detail", headers=doctor).status_code == 403
        detail = client.get("/api/v1/health/detail", headers=admin)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["app"]["environment"] == "development"
        assert body["database"]["reachable"] is True
        assert body["database"]["accounts"] == 2
        assert body["database"]["patients"] == 1
        # 开发默认不强制登录，明细里如实反映。
        assert body["security"]["auth_required"] is False
        assert body["security"]["openapi_docs_enabled"] is True
        assert body["models"]["deepfm_ready"] is False
        assert "model_endpoint" in body["imports"]


def test_request_id_is_logged_and_returned(test_app, db_session, caplog):
    with TestClient(test_app) as client:
        with caplog.at_level("INFO", logger="xunying.request"):
            response = client.get("/health", headers={"X-Request-ID": "trace-123"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "trace-123"
    lines = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "xunying.request"
    ]
    entry = [item for item in lines if item["path"] == "/health"][-1]
    assert entry["request_id"] == "trace-123"
    assert entry["status"] == 200
    assert entry["duration_ms"] >= 0
    assert "password" not in json.dumps(entry)


def test_production_disables_openapi_docs(monkeypatch, db_session):
    from app.core.config import Settings
    from app.main import create_app

    production = Settings(app_env="production", auth_required=True)
    monkeypatch.setattr("app.main.get_settings", lambda: production)
    application = create_app()
    with TestClient(application) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        assert client.get("/health").status_code == 200


def test_backup_and_restore_round_trip(tmp_path):
    database = tmp_path / "xunying.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Patient(anonymous_code="P-BACKUP-001", gender=Gender.FEMALE))
        session.commit()

    result = create_backup(f"sqlite:///{database}", tmp_path / "backups")
    assert result.archive_path.exists()
    assert result.manifest_path.exists()
    assert result.sha256
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sha256"] == result.sha256

    with Session(engine) as session:
        session.query(Patient).delete()
        session.commit()
        assert session.query(Patient).count() == 0

    with pytest.raises(BackupError):
        restore_backup(result.archive_path, f"sqlite:///{database}")  # 未确认覆盖
    restored = restore_backup(result.archive_path, f"sqlite:///{database}", force=True)
    assert restored["safety_copy"]
    with Session(engine) as session:
        assert session.query(Patient).count() == 1
        session.expire_all()
    assert Path(restored["restored_to"]).exists()


def test_backup_rejects_tampered_archive(tmp_path):
    database = tmp_path / "xunying.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(HealthCheck(patient_id="missing", check_date=date(2026, 1, 1)))
        session.rollback()
    result = create_backup(f"sqlite:///{database}", tmp_path / "backups")

    payload = bytearray(result.archive_path.read_bytes())
    payload[100] ^= 0xFF
    result.archive_path.write_bytes(bytes(payload))
    with pytest.raises(BackupError) as excinfo:
        restore_backup(result.archive_path, f"sqlite:///{tmp_path / 'target.db'}")
    assert "摘要" in str(excinfo.value) or "完整性" in str(excinfo.value)


def make_versioned_database(path, revision: str):
    """建一个带真实 alembic revision 标识的库，用于恢复版本判断测试。"""

    import sqlite3

    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version VALUES (?)", (revision,))
        connection.commit()
    return path


def test_backup_uses_alembic_graph_not_string_order(tmp_path):
    """审核 P1：用真实迁移标识判断先后，字符串排序会放过旧备份覆盖新库。"""

    from app.core.backup import compare_revisions

    # 真实迁移链：T02(f2a7c4d10e88) 早于 T03(b3c1d9e77a45)，但字符串顺序相反。
    assert compare_revisions("b3c1d9e77a45", "f2a7c4d10e88") == "archived_older"
    assert compare_revisions("f2a7c4d10e88", "b3c1d9e77a45") == "archived_newer"
    assert compare_revisions("f2a7c4d10e88", "f2a7c4d10e88") == "same"
    assert compare_revisions("b3c1d9e77a45", "not-a-real-revision") == "unknown"

    older = make_versioned_database(tmp_path / "older.db", "f2a7c4d10e88")
    backup = create_backup(f"sqlite:///{older}", tmp_path / "backups")
    assert backup.revision == "f2a7c4d10e88"

    # 旧备份覆盖较新数据库必须被拒绝（f2a 是 b3c 的祖先）。
    target = make_versioned_database(tmp_path / "target.db", "b3c1d9e77a45")
    with pytest.raises(BackupError) as excinfo:
        restore_backup(backup.archive_path, f"sqlite:///{target}", force=True)
    assert "早于" in str(excinfo.value)
    assert current_revision(target) == "b3c1d9e77a45"

    # 无法识别的版本必须显式阻止，不能靠字符串比较放行。
    unknown_target = make_versioned_database(tmp_path / "unknown.db", "made-up-revision")
    with pytest.raises(BackupError) as excinfo:
        restore_backup(backup.archive_path, f"sqlite:///{unknown_target}", force=True)
    assert "无法在迁移图中确认" in str(excinfo.value)


def test_backup_allows_newer_and_same_revision(tmp_path):
    """更新的备份覆盖旧库、以及同版本覆盖属于允许范围。"""

    newer = make_versioned_database(tmp_path / "newer.db", "b3c1d9e77a45")
    backup = create_backup(f"sqlite:///{newer}", tmp_path / "backups")
    older_target = make_versioned_database(tmp_path / "older-target.db", "f2a7c4d10e88")
    restored = restore_backup(backup.archive_path, f"sqlite:///{older_target}", force=True)
    assert restored["alembic_revision"] == "b3c1d9e77a45"
    assert current_revision(older_target) == "b3c1d9e77a45"

    same_target = make_versioned_database(tmp_path / "same-target.db", "b3c1d9e77a45")
    again = restore_backup(backup.archive_path, f"sqlite:///{same_target}", force=True)
    assert again["alembic_revision"] == "b3c1d9e77a45"


def test_backup_rejects_diverged_revision_graph(tmp_path, monkeypatch):
    """迁移链不相关（分叉）时必须阻止，并说明原因。"""

    from app.core import backup as backup_module

    monkeypatch.setattr(
        backup_module,
        "_ancestors",
        lambda revision: {"left"} if revision == "left-head" else {"right"},
    )
    assert backup_module.compare_revisions("left-head", "right-head") == "diverged"


def test_backup_rejects_non_sqlite(tmp_path):
    with pytest.raises(BackupError) as excinfo:
        create_backup("postgresql://user@host/db", tmp_path)
    assert "SQLite" in str(excinfo.value)
