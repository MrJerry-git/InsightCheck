import asyncio
from typing import Any

from httpx import ASGITransport, AsyncClient, Response

from app.api.routes.crud import CRUD_SPECS


async def request_from_app(app: Any, method: str, path: str, **kwargs: Any) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_every_entity_exposes_basic_crud_contract(test_app: Any) -> None:
    paths = test_app.openapi()["paths"]

    for spec in CRUD_SPECS:
        assert {"get", "post"}.issubset(paths[f"/api/v1{spec.path}"])
        assert {"get", "patch", "delete"}.issubset(paths[f"/api/v1{spec.path}/{{entity_id}}"])


def test_patient_crud_round_trip(test_app: Any) -> None:
    created = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/patients",
            json={
                "anonymous_code": " qa-patient-001 ",
                "gender": "unknown",
                "birth_date": "2001-01-01",
                "height": 168.5,
            },
        )
    )
    assert created.status_code == 201
    patient = created.json()
    assert patient["anonymous_code"] == "QA-PATIENT-001"

    fetched = asyncio.run(request_from_app(test_app, "GET", f"/api/v1/patients/{patient['id']}"))
    assert fetched.status_code == 200

    updated = asyncio.run(
        request_from_app(
            test_app,
            "PATCH",
            f"/api/v1/patients/{patient['id']}",
            json={"height": 169.0},
        )
    )
    assert updated.status_code == 200
    assert updated.json()["height"] == 169.0

    listed = asyncio.run(request_from_app(test_app, "GET", "/api/v1/patients"))
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    deleted = asyncio.run(request_from_app(test_app, "DELETE", f"/api/v1/patients/{patient['id']}"))
    assert deleted.status_code == 204

    missing = asyncio.run(request_from_app(test_app, "GET", f"/api/v1/patients/{patient['id']}"))
    assert missing.status_code == 404


def test_patient_unique_code_returns_conflict(test_app: Any) -> None:
    payload = {"anonymous_code": "SAME-CODE", "gender": "unknown"}
    first = asyncio.run(request_from_app(test_app, "POST", "/api/v1/patients", json=payload))
    second = asyncio.run(request_from_app(test_app, "POST", "/api/v1/patients", json=payload))

    assert first.status_code == 201
    assert second.status_code == 409
