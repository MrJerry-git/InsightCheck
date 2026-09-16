from typing import Any

from fastapi.testclient import TestClient

from app.ml.recommendation.model import DeepFMRecommendationModel
from app.ml.recommendation.schemas import (
    DeepFMConfig,
    RecommendationModelVariant,
    RecommendationRankingRequest,
)

from .test_deepfm import exam_items, patient, training_dataset


def test_ranking_api_runs_candidate_generation_then_deepfm(test_app: Any) -> None:
    model = DeepFMRecommendationModel(
        DeepFMConfig(
            model_version="deepfm-api-demo-v1",
            variant=RecommendationModelVariant.FULL,
            embedding_dim=4,
            hidden_dims=[8],
            epochs=40,
            batch_size=24,
            learning_rate=0.03,
            random_seed=17,
        )
    )
    model.train(training_dataset())
    test_app.state.recommendation_model = model
    payload = RecommendationRankingRequest(
        patient=patient("api-patient", 0.9),
        candidate_exam_items=list(reversed(exam_items())),
        trace_id="trace-api-ranking",
    )

    with TestClient(test_app) as client:
        response = client.post(
            "/api/v1/recommendation-ranking/rank",
            json=payload.model_dump(mode="json"),
        )

    assert response.status_code == 200
    body = response.json()
    assert [item["exam_item_id"] for item in body["items"]] == [
        "exam-a",
        "exam-b",
        "exam-c",
    ]
    assert body["candidate_generator_version"] == "candidate-generator-v1"
    assert body["safety_rules_applied"] is False
    assert body["requires_rule_engine"] is True
    assert body["score_semantics"] == "patient_exam_match_score_not_disease_probability"


def test_ranking_api_never_fakes_scores_when_model_artifact_is_missing(test_app: Any) -> None:
    payload = RecommendationRankingRequest(
        patient=patient("api-unconfigured-patient", 0.9),
        candidate_exam_items=exam_items(),
        trace_id="trace-api-unconfigured",
    )

    with TestClient(test_app) as client:
        response = client.post(
            "/api/v1/recommendation-ranking/rank",
            json=payload.model_dump(mode="json"),
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "推荐模型制品尚未加载"
