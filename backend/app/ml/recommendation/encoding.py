from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Any

import torch

from app.ml.recommendation.schemas import (
    ExamItemFeatures,
    PatientRecommendationFeatures,
    RecommendationModelVariant,
    RecommendationTrainingExample,
)

UNK_TOKEN = "__UNK__"
CATEGORICAL_FIELDS = (
    "patient_gender",
    "exam_code",
    "exam_category",
    "exam_body_part",
    "exam_cost_level",
)


@dataclass(frozen=True, slots=True)
class EncodedBatch:
    feature_ids: torch.Tensor
    feature_values: torch.Tensor


class RecommendationFeatureEncoder:
    """把 Patient × ExamItem 特征编码成 DeepFM 的定长 field 张量。"""

    def __init__(self, variant: RecommendationModelVariant) -> None:
        self.variant = variant
        self.categorical_vocabulary: dict[str, dict[str, int]] = {}
        self.numeric_feature_ids: dict[str, int] = {}
        self.numeric_means: dict[str, float] = {}
        self.numeric_stds: dict[str, float] = {}
        self.history_codes: tuple[str, ...] = ()
        self._fitted = False

    @property
    def field_count(self) -> int:
        return len(CATEGORICAL_FIELDS) + len(self.numeric_feature_ids)

    @property
    def feature_count(self) -> int:
        indexes = [
            index
            for vocabulary in self.categorical_vocabulary.values()
            for index in vocabulary.values()
        ] + list(self.numeric_feature_ids.values())
        return max(indexes, default=-1) + 1

    @property
    def risk_feature_names(self) -> tuple[str, ...]:
        return tuple(
            name.removeprefix("risk__")
            for name in self.numeric_feature_ids
            if name.startswith("risk__")
        )

    def fit(self, examples: Sequence[RecommendationTrainingExample]) -> None:
        if not examples:
            raise ValueError("at least one training example is required")
        self.history_codes = tuple(
            sorted({code for example in examples for code in example.patient.history_exam_codes})
        )
        categorical_values = {field: {UNK_TOKEN} for field in CATEGORICAL_FIELDS}
        raw_numeric_rows: list[dict[str, float | None]] = []
        for example in examples:
            categorical = self._categorical_values(example.patient, example.exam_item)
            for field, value in categorical.items():
                categorical_values[field].add(value)
            raw_numeric_rows.append(self._numeric_values(example.patient, example.exam_item))

        next_index = 0
        self.categorical_vocabulary = {}
        for field in CATEGORICAL_FIELDS:
            ordered_tokens = [UNK_TOKEN, *sorted(categorical_values[field] - {UNK_TOKEN})]
            self.categorical_vocabulary[field] = {}
            for token in ordered_tokens:
                self.categorical_vocabulary[field][token] = next_index
                next_index += 1

        numeric_names = sorted({name for row in raw_numeric_rows for name in row})
        self.numeric_feature_ids = {}
        self.numeric_means = {}
        self.numeric_stds = {}
        for name in numeric_names:
            self.numeric_feature_ids[name] = next_index
            next_index += 1
            present = [float(row[name]) for row in raw_numeric_rows if row.get(name) is not None]
            mean = fmean(present) if present else 0.0
            std = pstdev(present) if len(present) >= 2 else 1.0
            self.numeric_means[name] = mean
            self.numeric_stds[name] = std if std > 1e-12 else 1.0
        self._fitted = True

    def transform(
        self,
        pairs: Sequence[tuple[PatientRecommendationFeatures, ExamItemFeatures]],
    ) -> EncodedBatch:
        if not self._fitted:
            raise RuntimeError("feature encoder has not been fitted")
        id_rows: list[list[int]] = []
        value_rows: list[list[float]] = []
        for patient, exam_item in pairs:
            categorical = self._categorical_values(patient, exam_item)
            ids: list[int] = []
            values: list[float] = []
            for field in CATEGORICAL_FIELDS:
                vocabulary = self.categorical_vocabulary[field]
                ids.append(vocabulary.get(categorical[field], vocabulary[UNK_TOKEN]))
                values.append(1.0)
            numeric = self._numeric_values(patient, exam_item)
            for name, feature_id in self.numeric_feature_ids.items():
                ids.append(feature_id)
                raw_value = numeric.get(name)
                standardized = (
                    0.0
                    if raw_value is None
                    else (float(raw_value) - self.numeric_means[name]) / self.numeric_stds[name]
                )
                values.append(standardized)
            id_rows.append(ids)
            value_rows.append(values)
        if not pairs:
            return EncodedBatch(
                feature_ids=torch.empty((0, self.field_count), dtype=torch.long),
                feature_values=torch.empty((0, self.field_count), dtype=torch.float32),
            )
        return EncodedBatch(
            feature_ids=torch.tensor(id_rows, dtype=torch.long),
            feature_values=torch.tensor(value_rows, dtype=torch.float32),
        )

    def to_dict(self) -> dict[str, Any]:
        if not self._fitted:
            raise RuntimeError("feature encoder has not been fitted")
        return {
            "variant": self.variant.value,
            "categorical_vocabulary": self.categorical_vocabulary,
            "numeric_feature_ids": self.numeric_feature_ids,
            "numeric_means": self.numeric_means,
            "numeric_stds": self.numeric_stds,
            "history_codes": list(self.history_codes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RecommendationFeatureEncoder:
        encoder = cls(RecommendationModelVariant(payload["variant"]))
        encoder.categorical_vocabulary = {
            field: {token: int(index) for token, index in vocabulary.items()}
            for field, vocabulary in payload["categorical_vocabulary"].items()
        }
        encoder.numeric_feature_ids = {
            name: int(index) for name, index in payload["numeric_feature_ids"].items()
        }
        encoder.numeric_means = {
            name: float(value) for name, value in payload["numeric_means"].items()
        }
        encoder.numeric_stds = {
            name: float(value) for name, value in payload["numeric_stds"].items()
        }
        encoder.history_codes = tuple(payload["history_codes"])
        encoder._fitted = True
        return encoder

    @staticmethod
    def _categorical_values(
        patient: PatientRecommendationFeatures, exam_item: ExamItemFeatures
    ) -> dict[str, str]:
        return {
            "patient_gender": patient.gender,
            "exam_code": exam_item.exam_code,
            "exam_category": exam_item.category,
            "exam_body_part": exam_item.body_part or UNK_TOKEN,
            "exam_cost_level": exam_item.cost_level,
        }

    def _numeric_values(
        self, patient: PatientRecommendationFeatures, exam_item: ExamItemFeatures
    ) -> dict[str, float | None]:
        known_history = set(self.history_codes)
        values: dict[str, float | None] = {
            "patient_age": float(patient.age) if patient.age is not None else None,
            "patient_confidence": patient.confidence,
            "patient_history_count": float(len(patient.history_exam_codes)),
            "patient_unknown_history_count": float(
                sum(code not in known_history for code in patient.history_exam_codes)
            ),
            "exam_radiation": float(exam_item.radiation),
            "exam_recommended_interval_months": (
                float(exam_item.recommended_interval_months)
                if exam_item.recommended_interval_months is not None
                else None
            ),
            "months_since_candidate_exam": patient.months_since_exam_by_code.get(
                exam_item.exam_code
            ),
        }
        history = set(patient.history_exam_codes)
        values.update({f"history__{code}": float(code in history) for code in self.history_codes})
        values.update({f"current__{key}": value for key, value in patient.current_metrics.items()})
        values.update(
            {f"trend__{key}": value for key, value in patient.longitudinal_trends.items()}
        )
        values.update({f"lesion__{key}": value for key, value in patient.lesion_features.items()})
        if self.variant is RecommendationModelVariant.FULL:
            values.update(
                {f"risk__{key}": value for key, value in patient.risk_probabilities.items()}
            )
        return values
