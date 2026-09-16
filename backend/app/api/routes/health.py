from fastapi import APIRouter

from app.schemas.system import HealthStatus
from app.services.system_service import SystemService

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthStatus)
def health_check() -> HealthStatus:
    return SystemService().get_health_status()
