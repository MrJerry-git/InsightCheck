import json
from datetime import date, timedelta

import pytest

from app.ml.recommendation.model import DeepFMRecommendationModel
from app.ml.recommendation.schemas import (
    DeepFMConfig,
    ExamItemFeatures,
    PatientRecommendationFeatures,
    RecommendationModelVariant,
    RecommendationRankingRequest,
    RecommendationTrainingDataset,
    RecommendationTrainingExample,
)


def exam_items() -> list[ExamItemFeatures]:
    return [
        ExamItemFeatures(
            exam_item_id="exam-a",
            exam_code="A",
            category="laboratory",
            body_part="LIVER",
            radiation=False,
            cost_level="low",
            recommended_interval_months=12,
        ),
        ExamItemFeatures(
            exam_item_id="exam-b",
            exam_code="B",
            category="imaging",
            body_part="CHEST",
            radiation=True,
            cost_level="medium",
            recommended_interval_months=24,
        ),
        ExamItemFeatures(
            exam_item_id="exam-c",
            exam_code="C",
            category="laboratory",
            body_part="KIDNEY",
            radiation=False,
            cost_level="high",
            recommended_interval_months=6,
        ),
    ]


def patient(patient_id: str, risk: float, *, has_history: bool = True):
    cutoff = date(2025, 1, 1)
    return PatientRecommendationFeatures(
        patient_id=patient_id,
        feature_as_of_date=cutoff,
        feature_pipeline_version="metric-feature-pipeline-v1.1",
        age=30 if has_history else None,
        gender="female" if has_history else "unknown",
        history_exam_codes=["B"] if has_history else [],
        history_latest_date=date(2024, 1, 1) if has_history else None,
        current_metrics={"ALT": 20.0 + risk},
        longitudinal_trends={"ALT_SLOPE": risk},
        lesion_features={"GROWTH_RATE": risk / 2},
        risk_probabilities={"LIVER_RISK": risk},
        risk_as_of_date=cutoff,
        risk_model_version="demo-risk-model-v1",
        confidence=0.9,
        months_since_exam_by_code={"A": 18.0, "B": 8.0},
        evidence_refs=[f"feature:{patient_id}"],
        is_demo=True,
    )


def training_dataset() -> RecommendationTrainingDataset:
    items = exam_items()
    examples: list[RecommendationTrainingExample] = []
    for index in range(8):
        risk = 0.9 if index >= 4 else 0.1
        current_patient = patient(f"demo-patient-{index}", risk)
        labels = {"exam-a": float(risk > 0.5), "exam-b": float(index in {2, 6}), "exam-c": 0.0}
        for item in items:
            examples.append(
                RecommendationTrainingExample(
                    patient=current_patient,
                    exam_item=item,
                    label=labels[item.exam_item_id],
                    label_observed_at=current_patient.feature_as_of_date + timedelta(days=365),
                    is_demo=True,
                )
            )
    return RecommendationTrainingDataset(
        examples=examples,
        dataset_version="demo-recommendation-dataset-v1",
        feature_pipeline_version="metric-feature-pipeline-v1.1",
        is_demo=True,
    )


@pytest.fixture(scope="module")
def trained_model() -> DeepFMRecommendationModel:
    model = DeepFMRecommendationModel(
        DeepFMConfig(
            model_version="deepfm-demo-v1",
            variant=RecommendationModelVariant.FULL,
            embedding_dim=4,
            hidden_dims=[12, 6],
            epochs=80,
            batch_size=24,
            learning_rate=0.03,
            random_seed=17,
        )
    )
    model.train(training_dataset())
    return model


def test_model_scores_batch_one_and_batch_many_with_sigmoid_range(
    trained_model: DeepFMRecommendationModel,
) -> None:
    current_patient = patient("ranking-patient", 0.9)

    one = trained_model.rank(
        RecommendationRankingRequest(
            patient=current_patient,
            candidate_exam_items=exam_items()[:1],
            trace_id="trace-one",
        )
    )
    many = trained_model.rank(
        RecommendationRankingRequest(
            patient=current_patient,
            candidate_exam_items=exam_items(),
            trace_id="trace-many",
        )
    )

    assert len(one) == 1
    assert len(many) == 3
    assert all(0.0 <= item.deepfm_score <= 1.0 for item in [*one, *many])
    assert all(item.model_version == "deepfm-demo-v1" for item in many)
    assert all(item.feature_version == "metric-feature-pipeline-v1.1" for item in many)


def test_learned_scores_rank_a_above_b_above_c(
    trained_model: DeepFMRecommendationModel,
) -> None:
    ranking = trained_model.rank(
        RecommendationRankingRequest(
            patient=patient("ranking-patient", 0.9),
            candidate_exam_items=exam_items(),
            trace_id="trace-ranking",
        )
    )

    assert [item.exam_item_id for item in ranking] == ["exam-a", "exam-b", "exam-c"]
    assert ranking[0].deepfm_score > ranking[1].deepfm_score > ranking[2].deepfm_score


def test_cold_start_patient_and_unknown_exam_item_use_controlled_unknown_encoding(
    trained_model: DeepFMRecommendationModel,
) -> None:
    unknown_item = ExamItemFeatures(
        exam_item_id="exam-new",
        exam_code="NEVER_SEEN",
        category="never-seen-category",
        body_part="UNKNOWN_PART",
        radiation=False,
        cost_level="unknown",
    )

    ranking = trained_model.rank(
        RecommendationRankingRequest(
            patient=patient("cold-start-patient", 0.4, has_history=False),
            candidate_exam_items=[unknown_item],
            trace_id="trace-cold-start",
        )
    )

    assert len(ranking) == 1
    assert ranking[0].exam_item_id == "exam-new"
    assert 0.0 <= ranking[0].deepfm_score <= 1.0


def test_save_and_load_preserve_ranking_and_complete_artifact(
    trained_model: DeepFMRecommendationModel, tmp_path
) -> None:
    request = RecommendationRankingRequest(
        patient=patient("artifact-patient", 0.9),
        candidate_exam_items=exam_items(),
        trace_id="trace-artifact",
    )
    expected = trained_model.rank(request)
    assert trained_model.metadata is not None

    trained_model.save(tmp_path, trained_model.metadata)
    restored = DeepFMRecommendationModel.load(tmp_path)
    actual = restored.rank(request)

    assert {path.name for path in tmp_path.iterdir()} == {
        "weights.pt",
        "embedding_config.json",
        "feature_mapping.json",
        "metadata.json",
    }
    mapping = json.loads((tmp_path / "feature_mapping.json").read_text(encoding="utf-8"))
    assert set(mapping["categorical_vocabulary"]) == {
        "patient_gender",
        "exam_code",
        "exam_category",
        "exam_body_part",
        "exam_cost_level",
    }
    assert {
        "history__B",
        "current__ALT",
        "trend__ALT_SLOPE",
        "lesion__GROWTH_RATE",
        "risk__LIVER_RISK",
        "months_since_candidate_exam",
    } <= set(mapping["numeric_feature_ids"])
    assert [item.exam_item_id for item in actual] == [item.exam_item_id for item in expected]
    assert [item.deepfm_score for item in actual] == pytest.approx(
        [item.deepfm_score for item in expected]
    )


def test_evaluation_returns_all_required_top_k_metrics(
    trained_model: DeepFMRecommendationModel,
) -> None:
    result = trained_model.evaluate(training_dataset())

    assert set(result.metrics) == {
        "Precision@5",
        "Recall@5",
        "NDCG@5",
        "Precision@10",
        "Recall@10",
        "NDCG@10",
    }
    assert all(0.0 <= value <= 1.0 for value in result.metrics.values())
    assert result.dataset_version == "demo-recommendation-dataset-v1"


def test_full_deepfm_consumes_risk_feature_in_observable_score(
    trained_model: DeepFMRecommendationModel,
) -> None:
    low_risk = patient("risk-low", 0.1)
    high_risk = low_risk.model_copy(
        update={
            "patient_id": "risk-high",
            "risk_probabilities": {"LIVER_RISK": 0.9},
        }
    )
    candidate = [exam_items()[0]]

    low_score = trained_model.rank(
        RecommendationRankingRequest(
            patient=low_risk,
            candidate_exam_items=candidate,
            trace_id="trace-risk-low",
        )
    )[0].deepfm_score
    high_score = trained_model.rank(
        RecommendationRankingRequest(
            patient=high_risk,
            candidate_exam_items=candidate,
            trace_id="trace-risk-high",
        )
    )[0].deepfm_score

    assert trained_model.risk_feature_names == ("LIVER_RISK",)
    assert high_score > low_score


def test_without_risk_ablation_is_executable_and_ignores_only_risk_fields() -> None:
    model = DeepFMRecommendationModel(
        DeepFMConfig(
            model_version="deepfm-without-risk-demo-v1",
            variant=RecommendationModelVariant.WITHOUT_RISK,
            embedding_dim=4,
            hidden_dims=[8],
            epochs=40,
            batch_size=24,
            learning_rate=0.03,
            random_seed=17,
        )
    )
    model.train(training_dataset())
    low_risk = patient("ablation-low", 0.1)
    high_risk = low_risk.model_copy(
        update={
            "patient_id": "ablation-high",
            "risk_probabilities": {"LIVER_RISK": 0.9},
        }
    )
    candidate = [exam_items()[0]]

    low_score = model.rank(
        RecommendationRankingRequest(
            patient=low_risk,
            candidate_exam_items=candidate,
            trace_id="trace-ablation-low",
        )
    )[0].deepfm_score
    high_score = model.rank(
        RecommendationRankingRequest(
            patient=high_risk,
            candidate_exam_items=candidate,
            trace_id="trace-ablation-high",
        )
    )[0].deepfm_score

    assert model.risk_feature_names == ()
    assert high_score == pytest.approx(low_score)
