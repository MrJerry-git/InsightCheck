import asyncio
from typing import Any

from httpx import ASGITransport, AsyncClient, Response


async def request_from_app(app: Any, method: str, path: str, **kwargs: Any) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def interval_request() -> dict[str, object]:
    return {
        "patient": {
            "patient_id": "patient-api",
            "as_of_date": "2026-03-01",
            "age": 42,
            "sex": "male",
        },
        "exam_item": {
            "exam_item_id": "exam-item-api",
            "code": "CHEST_CT",
            "name": "胸部 CT",
            "category": "imaging",
            "body_part": "CHEST",
            "radiation": True,
            "recommended_interval_months": 12,
        },
        "deepfm_score": 0.95,
        "exam_history": [
            {
                "exam_item_id": "exam-item-api",
                "exam_code": "CHEST_CT",
                "performed_at": "2026-01-01",
                "result_status": "completed",
            }
        ],
        "trace_id": "trace-api-interval",
    }


def test_rule_engine_api_reads_current_database_rule_without_stale_cache(test_app: Any) -> None:
    created = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/medical-rules",
            json={
                "rule_code": "INTERVAL.API.TEST",
                "rule_type": "INTERVAL",
                "condition_json": {"minimum_months": 12},
                "action": "DEFER",
                "priority": 80,
                "source": "演示规则：API 测试基线，不作为临床指南",
                "version": "demo-api-v1",
                "enabled": True,
            },
        )
    )
    assert created.status_code == 201

    first = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/rule-engine/evaluate",
            json=interval_request(),
        )
    )
    assert first.status_code == 200
    assert first.json()["final_status"] == "DEFERRED"

    updated = asyncio.run(
        request_from_app(
            test_app,
            "PATCH",
            f"/api/v1/medical-rules/{created.json()['id']}",
            json={"enabled": False},
        )
    )
    assert updated.status_code == 200

    second = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/rule-engine/evaluate",
            json=interval_request(),
        )
    )
    assert second.status_code == 200
    assert second.json()["final_status"] == "ALLOWED"
    assert second.json()["execution_trace"][0]["enabled"] is False


def test_medical_rule_api_rejects_empty_source(test_app: Any) -> None:
    response = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/medical-rules",
            json={
                "rule_code": "INVALID.EMPTY.SOURCE",
                "rule_type": "AGE",
                "condition_json": {"allowed_min_age": 18},
                "action": "BLOCK",
                "priority": 80,
                "source": "   ",
                "version": "invalid-v1",
                "enabled": True,
            },
        )
    )

    assert response.status_code == 422
