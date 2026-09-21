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


def test_backup_rejects_newer_database(tmp_path):
    import sqlite3

    database = tmp_path / "xunying.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute("INSERT INTO alembic_version VALUES ('aaa-old')")
        connection.commit()
    backup = create_backup(f"sqlite:///{database}", tmp_path / "backups")
    assert backup.revision == "aaa-old"

    # 目标库迁移版本更新时拒绝用旧备份覆盖。
    target = tmp_path / "target.db"
    with sqlite3.connect(database) as source, sqlite3.connect(target) as dest:
        source.backup(dest)
    with sqlite3.connect(target) as connection:
        connection.execute("DELETE FROM alembic_version")
        connection.execute("INSERT INTO alembic_version VALUES ('zzz-newer')")
        connection.commit()
    with pytest.raises(BackupError) as excinfo:
        restore_backup(backup.archive_path, f"sqlite:///{target}", force=True)
    assert "早于" in str(excinfo.value)
    assert current_revision(target) == "zzz-newer"


def test_backup_rejects_non_sqlite(tmp_path):
    with pytest.raises(BackupError) as excinfo:
        create_backup("postgresql://user@host/db", tmp_path)
    assert "SQLite" in str(excinfo.value)
