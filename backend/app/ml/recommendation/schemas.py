from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RecommendationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ExamItemFeatures(RecommendationSchema):
    exam_item_id: str = Field(min_length=1, max_length=100)
    exam_code: str = Field(min_length=1, max_length=64)
    category: str = Field(min_length=1, max_length=100)
    body_part: str | None = Field(default=None, max_length=100)
    radiation: bool = False
    cost_level: Literal["low", "medium", "high", "unknown"] = "unknown"
    recommended_interval_months: int | None = Field(default=None, gt=0)

    @field_validator("exam_code")
    @classmethod
    def normalize_exam_code(cls, value: str) -> str:
        return value.strip().upper()


class CandidateSet(RecommendationSchema):
    items: list[ExamItemFeatures]
    generator_version: str
    safety_rules_applied: bool = False
    requires_rule_engine: bool = True


class PatientRecommendationFeatures(RecommendationSchema):
    patient_id: str = Field(min_length=1, max_length=100)
    feature_as_of_date: date
    feature_pipeline_version: str = Field(min_length=1, max_length=64)
    age: int | None = Field(default=None, ge=0, le=120)
    gender: Literal["female", "male", "other", "unknown"] = "unknown"
    history_exam_codes: list[str] = Field(default_factory=list)
    history_latest_date: date | None = None
    current_metrics: dict[str, float | None] = Field(default_factory=dict)
    longitudinal_trends: dict[str, float | None] = Field(default_factory=dict)
    lesion_features: dict[str, float | None] = Field(default_factory=dict)
    risk_probabilities: dict[str, float] = Field(default_factory=dict)
    risk_as_of_date: date | None = None
    risk_model_version: str | None = Field(default=None, max_length=64)
    confidence: float | None = Field(default=None, ge=0, le=1)
    months_since_exam_by_code: dict[str, float] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    is_demo: bool = False

    @field_validator("history_exam_codes")
    @classmethod
    def normalize_history_codes(cls, values: list[str]) -> list[str]:
        return [value.strip().upper() for value in values]

    @field_validator("risk_probabilities")
    @classmethod
    def validate_risk_probabilities(cls, values: dict[str, float]) -> dict[str, float]:
        if any(value < 0 or value > 1 for value in values.values()):
            raise ValueError("risk probabilities must be between 0 and 1")
        return values

    @field_validator("months_since_exam_by_code")
    @classmethod
    def validate_time_intervals(cls, values: dict[str, float]) -> dict[str, float]:
        if any(value < 0 for value in values.values()):
            raise ValueError("months since exam must be nonnegative")
        return {key.strip().upper(): value for key, value in values.items()}


class RecommendationTrainingExample(RecommendationSchema):
    patient: PatientRecommendationFeatures
    exam_item: ExamItemFeatures
    label: float = Field(ge=0, le=1)
    label_observed_at: date
    is_demo: bool = False

    @model_validator(mode="after")
    def validate_temporal_order(self) -> "RecommendationTrainingExample":
        cutoff = self.patient.feature_as_of_date
        if self.label_observed_at <= cutoff:
            raise ValueError("label_observed_at must be after feature_as_of_date")
        if (
            self.patient.history_latest_date is not None
            and self.patient.history_latest_date > cutoff
        ):
            raise ValueError("history_latest_date must not be after feature_as_of_date")
        if self.patient.risk_probabilities:
            if self.patient.risk_as_of_date is None:
                raise ValueError("risk_as_of_date is required when risk features are present")
            if self.patient.risk_as_of_date > cutoff:
                raise ValueError("risk_as_of_date must not be after feature_as_of_date")
            if not self.patient.risk_model_version:
                raise ValueError("risk_model_version is required when risk features are present")
        if self.is_demo != self.patient.is_demo:
            raise ValueError("example and patient is_demo flags must match")
        return self


class RecommendationModelVariant(StrEnum):
    AGE_GENDER_BASELINE = "age_gender_baseline"
    RULE_ONLY_BASELINE = "rule_only_baseline"
    WITHOUT_RISK = "deepfm_without_risk"
    FULL = "full_deepfm"


class DeepFMConfig(RecommendationSchema):
    model_version: str = Field(default="deepfm-v1", min_length=1, max_length=64)
    variant: RecommendationModelVariant = RecommendationModelVariant.FULL
    embedding_dim: int = Field(default=8, ge=2, le=128)
    hidden_dims: list[int] = Field(default_factory=lambda: [64, 32])
    dropout: float = Field(default=0.1, ge=0, lt=1)
    epochs: int = Field(default=20, ge=1, le=10_000)
    batch_size: int = Field(default=64, ge=1)
    learning_rate: float = Field(default=0.001, gt=0)
    weight_decay: float = Field(default=1e-5, ge=0)
    random_seed: int = Field(default=42, ge=0)

    @field_validator("hidden_dims")
    @classmethod
    def validate_hidden_dims(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("hidden dimensions must be positive")
        return values


class RecommendationTrainingDataset(RecommendationSchema):
    examples: list[RecommendationTrainingExample] = Field(min_length=1)
    dataset_version: str = Field(min_length=1, max_length=100)
    feature_pipeline_version: str = Field(min_length=1, max_length=64)
    is_demo: bool = False

    @model_validator(mode="after")
    def validate_consistent_versions(self) -> "RecommendationTrainingDataset":
        for example in self.examples:
            if example.patient.feature_pipeline_version != self.feature_pipeline_version:
                raise ValueError("patient feature version does not match dataset")
            if example.is_demo != self.is_demo:
                raise ValueError("dataset and example is_demo flags must match")
        return self


class RecommendationRankingRequest(RecommendationSchema):
    patient: PatientRecommendationFeatures
    candidate_exam_items: list[ExamItemFeatures]
    trace_id: str = Field(min_length=1, max_length=100)


class DeepFMRankedExamItem(RecommendationSchema):
    exam_item_id: str
    deepfm_score: float = Field(ge=0, le=1)
    model_version: str
    feature_version: str
    trace_id: str


class RecommendationRankingResponse(RecommendationSchema):
    items: list[DeepFMRankedExamItem]
    candidate_generator_version: str
    safety_rules_applied: bool = False
    requires_rule_engine: bool = True
    score_semantics: Literal["patient_exam_match_score_not_disease_probability"] = (
        "patient_exam_match_score_not_disease_probability"
    )
    disclaimer: str
