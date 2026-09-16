from app.core.config import get_settings
from app.core.database import engine
from app.main import app


def test_application_bootstrap_does_not_require_database_connection() -> None:
    settings = get_settings()

    assert app.title == settings.app_name
    assert str(engine.url) == settings.database_url
    assert engine.pool is not None


def test_expected_routers_are_registered() -> None:
    route_paths = set(app.openapi()["paths"])

    assert "/health" in route_paths
    assert "/api/v1/health" in route_paths
