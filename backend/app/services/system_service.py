from app.core.config import get_settings
from app.schemas.system import HealthStatus


class SystemService:
    def get_health_status(self) -> HealthStatus:
        settings = get_settings()
        return HealthStatus(
            status="ok",
            service=settings.app_name,
            version=settings.app_version,
            environment=settings.app_env,
        )
