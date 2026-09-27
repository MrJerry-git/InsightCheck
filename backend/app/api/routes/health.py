import os
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import Principal, get_db, require_admin
from app.core.config import get_settings
from app.models import Account, Patient
from app.schemas.system import HealthStatus
from app.services.system_service import SystemService

router = APIRouter(tags=["system"])

STARTED_AT = datetime.now(UTC)


@router.get("/health", response_model=HealthStatus)
def health_check() -> HealthStatus:
    return SystemService().get_health_status()


def _alembic_revision(db: Session) -> str | None:
    try:
        row = db.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    except Exception:  # noqa: BLE001 - 迁移表可能尚不存在
        return None
    return None if row is None else str(row[0])


@router.get("/health/detail")
def health_detail(
    _: Principal = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
):
    """部署健康明细：数据库、迁移版本、模型状态与运行配置（仅管理员可读）。"""

    settings = get_settings()
    storage = Path(settings.import_task_storage_dir)
    try:
        storage.mkdir(parents=True, exist_ok=True)
        storage_writable = os.access(storage, os.W_OK)
        storage_error = None
    except OSError as exc:
        storage_writable = False
        storage_error = str(exc)
    database_ok = True
    database_error = None
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 健康检查需要捕获所有数据库异常
        database_ok = False
        database_error = type(exc).__name__
    return {
        "app": {
            "name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
            "started_at": STARTED_AT.isoformat(),
            "uptime_seconds": int((datetime.now(UTC) - STARTED_AT).total_seconds()),
        },
        "database": {
            "dialect": db.bind.dialect.name if db.bind is not None else "unknown",
            "reachable": database_ok,
            "error": database_error,
            "alembic_revision": _alembic_revision(db),
            "accounts": db.query(Account).count(),
            "patients": db.query(Patient).count(),
        },
        "security": {
            "auth_required": settings.auth_required,
            "session_ttl_minutes": settings.session_ttl_minutes,
            "password_hash_iterations": settings.password_hash_iterations,
            "openapi_docs_enabled": settings.app_env != "production",
        },
        "imports": {
            "temporary_storage_dir": str(storage),
            "writable": storage_writable,
            "error": storage_error,
            "model_endpoint": settings.import_model_url,
            "model": settings.import_model,
        },
        "models": {
            "recommendation_artifact_path": settings.recommendation_artifact_path,
            "deepfm_ready": bool(settings.recommendation_artifact_path),
            "llm_provider": settings.llm_provider,
        },
    }
