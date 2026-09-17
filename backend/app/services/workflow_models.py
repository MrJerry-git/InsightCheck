"""Synthetic-only models for the 1.0 interactive engineering demonstration."""

from datetime import date
from functools import lru_cache
from threading import RLock

import numpy as np

from app.ml.recommendation.model import DeepFMRecommendationModel
from app.ml.recommendation.schemas import (
    DeepFMConfig,
    ExamItemFeatures,
    PatientRecommendationFeatures,
    RecommendationRankingRequest,
    RecommendationTrainingDataset,
    RecommendationTrainingExample,
)

LOCK = RLock()
VERSION = "workflow-synthetic-v1"


@lru_cache(maxsize=8)
def models(catalog: tuple):
    from lightgbm import LGBMClassifier

    rng = np.random.default_rng(1709)
    x = np.column_stack([rng.integers(18, 85, 128), rng.integers(1, 12, 128)])
    # Artificial task, deliberately unrelated to any disease or clinical threshold.
    y = ((x[:, 0] + x[:, 1] * 3 + rng.normal(0, 12, 128)) > 65).astype(int)
    risk = LGBMClassifier(
        n_estimators=24,
        num_leaves=7,
        verbosity=-1,
        n_jobs=1,
        random_state=1709,
        deterministic=True,
        force_col_wise=True,
    )
    risk.fit(x, y)
    items = [
        ExamItemFeatures(exam_item_id=i, exam_code=c, category=k, radiation=r, cost_level=cost)
        for i, c, k, r, cost in catalog
    ]
    examples = []
    for n in range(32):
        patient = PatientRecommendationFeatures(
            patient_id=f"fixture-{n}",
            feature_as_of_date=date(2024, 1, 1),
            feature_pipeline_version=VERSION,
            age=int(x[n, 0]),
            is_demo=True,
            risk_probabilities={"synthetic_task": float(risk.predict_proba(x[n : n + 1])[0, 1])},
            risk_as_of_date=date(2024, 1, 1),
            risk_model_version=VERSION,
        )
        for j, item in enumerate(items):
            examples.append(
                RecommendationTrainingExample(
                    patient=patient,
                    exam_item=item,
                    label=float((n + j) % 3 == 0),
                    label_observed_at=date(2024, 2, 1),
                    is_demo=True,
                )
            )
    ranker = DeepFMRecommendationModel(
        DeepFMConfig(
            model_version=VERSION,
            epochs=3,
            hidden_dims=[16],
            embedding_dim=4,
            random_seed=1709,
        )
    )
    ranker.train(
        RecommendationTrainingDataset(
            examples=examples,
            dataset_version=VERSION,
            feature_pipeline_version=VERSION,
            is_demo=True,
        )
    )
    return risk, ranker, items


def predict(catalog: tuple, patient_id: str, age: int, count: int, cutoff: date, trace: str):
    with LOCK:
        risk, ranker, items = models(catalog)
        probability = float(risk.predict_proba(np.array([[age, count]]))[0, 1])
        patient = PatientRecommendationFeatures(
            patient_id=patient_id,
            age=age,
            feature_as_of_date=cutoff,
            feature_pipeline_version=VERSION,
            is_demo=True,
            risk_probabilities={"synthetic_task": probability},
            risk_as_of_date=cutoff,
            risk_model_version=VERSION,
        )
        ranked = ranker.rank(
            RecommendationRankingRequest(
                patient=patient,
                candidate_exam_items=items,
                trace_id=trace,
            )
        )
        return probability, {item.exam_item_id: item.deepfm_score for item in ranked}
