import asyncio
from typing import Any

from httpx import ASGITransport, AsyncClient, Response

from app.services.lesion_demo_seed_service import LesionMatchingDemoSeedService


async def request_from_app(app: Any, method: str, path: str, **kwargs: Any) -> Response:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def test_matching_api_returns_explainable_decision(test_app: Any) -> None:
    response = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/lesion-analysis/match",
            json={
                "current_exam_date": "2024-06-01",
                "previous_tracks": [
                    {
                        "track_id": "track-1",
                        "observations": [
                            {
                                "lesion_id": "old-1",
                                "exam_date": "2023-06-01",
                                "lesion_type": "肺结节",
                                "organ": "肺",
                                "body_part": "胸部",
                                "location": "右上肺",
                                "size_mm": 5.0,
                                "grade": "G1",
                            }
                        ],
                    }
                ],
                "current_lesions": [
                    {
                        "lesion_id": "new-1",
                        "exam_date": "2024-06-01",
                        "lesion_type": "肺结节",
                        "organ": "肺",
                        "body_part": "胸部",
                        "location": "RUL",
                        "size_mm": 5.3,
                        "grade": "G1",
                    }
                ],
                "complete_body_parts": ["胸部"],
            },
        )
    )

    assert response.status_code == 200
    decision = response.json()["matches"][0]
    assert decision["status"] == "MATCHED"
    assert decision["matched_track_id"] == "track-1"
    assert decision["component_scores"]["location"] == 1
    assert decision["reasons"]


def test_trend_api_returns_requested_change_features(test_app: Any) -> None:
    response = asyncio.run(
        request_from_app(
            test_app,
            "POST",
            "/api/v1/lesion-analysis/trend",
            json={
                "track_id": "track-demo",
                "observations": [
                    {
                        "lesion_id": f"lesion-{year}",
                        "exam_date": f"{year}-06-01",
                        "lesion_type": "肺结节",
                        "organ": "肺",
                        "body_part": "胸部",
                        "location": "右肺上叶",
                        "size_mm": size,
                        "grade": grade,
                    }
                    for year, size, grade in [
                        (2023, 5.0, "G1"),
                        (2024, 5.3, "G1"),
                        (2025, 5.8, "G2"),
                        (2026, 6.2, "G2"),
                    ]
                ],
                "evaluation_date": "2026-06-01",
                "initial_match_status": "NEW_LESION",
                "presence_status": "CONTINUING",
            },
        )
    )

    assert response.status_code == 200
    result = response.json()
    assert result["absolute_size_change"] == 1.2
    assert result["growth_rate"] == 0.4
    assert result["continuous_occurrences"] == 4
    assert result["growing"] is True


def test_demo_api_uses_seeded_structured_lesions_and_real_analysis(
    test_app: Any, db_session: Any
) -> None:
    LesionMatchingDemoSeedService(db_session).run()

    response = asyncio.run(request_from_app(test_app, "GET", "/api/v1/lesion-analysis/demo"))

    assert response.status_code == 200
    result = response.json()
    assert result["is_demo"] is True
    assert result["demo_label"] == "DEMO DATA"
    assert [item["size_mm"] for item in result["trend"]["observations"]] == [
        5.0,
        5.3,
        5.8,
        6.2,
    ]
    assert [item["status"] for item in result["matches"]] == [
        "NEW_LESION",
        "MATCHED",
        "MATCHED",
        "MATCHED",
    ]
    assert all(
        item["matched_track_id"] is None
        for item in result["matches"]
        if item["status"] != "MATCHED"
    )
