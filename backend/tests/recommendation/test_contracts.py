from datetime import date

import pytest
from pydantic import ValidationError

from app.ml.recommendation.schemas import (
    ExamItemFeatures,
    PatientRecommendationFeatures,
    RecommendationTrainingExample,
)


def test_training_contract_rejects_history_from_after_feature_cutoff() -> None:
    patient = PatientRecommendationFeatures(
        patient_id="demo-patient",
        feature_as_of_date=date(2025, 1, 1),
        feature_pipeline_version="metric-feature-pipeline-v1.1",
        history_exam_codes=["CBC"],
        history_latest_date=date(2026, 1, 1),
        is_demo=True,
    )

    with pytest.raises(ValidationError, match="history_latest_date"):
        RecommendationTrainingExample(
            patient=patient,
            exam_item=ExamItemFeatures(
                exam_item_id="exam-cbc",
                exam_code="CBC",
                category="laboratory",
            ),
            label=1.0,
            label_observed_at=date(2026, 2, 1),
            is_demo=True,
        )


def test_training_contract_rejects_nonfuture_label_and_future_risk_features() -> None:
    cutoff = date(2025, 1, 1)
    item = ExamItemFeatures(
        exam_item_id="exam-cbc",
        exam_code="CBC",
        category="laboratory",
    )
    base_patient = PatientRecommendationFeatures(
        patient_id="demo-patient",
        feature_as_of_date=cutoff,
        feature_pipeline_version="metric-feature-pipeline-v1.1",
        is_demo=True,
    )
    with pytest.raises(ValidationError, match="label_observed_at"):
        RecommendationTrainingExample(
            patient=base_patient,
            exam_item=item,
            label=1.0,
            label_observed_at=cutoff,
            is_demo=True,
        )

    future_risk_patient = base_patient.model_copy(
        update={
            "risk_probabilities": {"LIVER_RISK": 0.8},
            "risk_as_of_date": date(2026, 1, 1),
            "risk_model_version": "demo-risk-v1",
        }
    )
    with pytest.raises(ValidationError, match="risk_as_of_date"):
        RecommendationTrainingExample(
            patient=future_risk_patient,
            exam_item=item,
            label=1.0,
            label_observed_at=date(2026, 2, 1),
            is_demo=True,
        )
