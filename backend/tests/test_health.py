import asyncio

import pytest
from httpx import ASGITransport, AsyncClient, Response

from app.main import app


async def get_from_app(path: str) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


@pytest.mark.parametrize("path", ["/health", "/api/v1/health"])
def test_health_check(path: str) -> None:
    response = asyncio.run(get_from_app(path))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "循影定检 API",
        "version": "0.1.0",
        "environment": "development",
    }


def test_health_routes_are_registered() -> None:
    registered_paths = set(app.openapi()["paths"])

    assert "/health" in registered_paths
    assert "/api/v1/health" in registered_paths
