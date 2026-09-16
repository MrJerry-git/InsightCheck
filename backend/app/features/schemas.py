from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import MetricStatus


class FeatureSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetricTrend(StrEnum):
    UNKNOWN = "UNKNOWN"
    RISING = "RISING"
    FALLING = "FALLING"
    STABLE = "STABLE"
    FLUCTUATING = "FLUCTUATING"


class EarlyWarningStatus(StrEnum):
    NONE = "NONE"
    EARLY_WARNING = "EARLY_WARNING"


class FeatureGroup(StrEnum):
    METABOLIC = "metabolic"
    CARDIOVASCULAR = "cardiovascular"
    LIVER = "liver"
    KIDNEY = "kidney"
    OTHER = "other"


class TrendConfig(FeatureSchema):
    stable_normalized_slope_threshold: float = Field(default=0.02, ge=0)
    stable_first_last_relative_threshold: float = Field(default=0.05, ge=0)
    fluctuation_cv_threshold: float = Field(default=0.15, ge=0)
    direction_consistency_threshold: float = Field(default=0.75, ge=0, le=1)
    numeric_epsilon: float = Field(default=1e-9, gt=0)
    days_per_year: float = Field(default=365.2425, gt=0)


class EarlyWarningConfig(FeatureSchema):
    minimum_observations: int = Field(default=3, ge=3)
    boundary_distance_fraction: float = Field(default=0.15, gt=0, le=1)
    max_gap_months: float = Field(default=18.0, gt=0)
    average_days_per_month: float = Field(default=30.4375, gt=0)
    direction_epsilon: float = Field(default=1e-9, ge=0)


class FeaturePipelineConfig(FeatureSchema):
    version: str = "metric-feature-pipeline-v1.1"
    trend: TrendConfig = Field(default_factory=TrendConfig)
    early_warning: EarlyWarningConfig = Field(default_factory=EarlyWarningConfig)
    category_aliases: dict[FeatureGroup, list[str]] = Field(
        default_factory=lambda: {
            FeatureGroup.METABOLIC: ["METABOLIC", "代谢"],
            FeatureGroup.CARDIOVASCULAR: ["CARDIOVASCULAR", "心血管"],
            FeatureGroup.LIVER: ["LIVER", "肝功能", "肝脏"],
            FeatureGroup.KIDNEY: ["KIDNEY", "肾功能", "肾脏"],
        }
    )
    trend_codes: dict[MetricTrend, int | None] = Field(
        default_factory=lambda: {
            MetricTrend.UNKNOWN: None,
            MetricTrend.FALLING: -1,
            MetricTrend.STABLE: 0,
            MetricTrend.RISING: 1,
            MetricTrend.FLUCTUATING: 2,
        }
    )


class MetricObservation(FeatureSchema):
    source_id: str = Field(min_length=1, max_length=100)
    metric_code: str = Field(min_length=1, max_length=64)
    canonical_name: str = Field(min_length=1, max_length=200)
    observed_at: date
    value: float | None = None
    reference_min: float | None = None
    reference_max: float | None = None
    status: MetricStatus = MetricStatus.UNKNOWN
    standard_unit: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    feature_group: FeatureGroup | None = None

    @field_validator("metric_code")
    @classmethod
    def normalize_metric_code(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_reference_range(self) -> "MetricObservation":
        if self.reference_min is not None and self.reference_max is not None:
            if self.reference_min > self.reference_max:
                raise ValueError("reference_min must not exceed reference_max")
        return self


class PatientFeatureRequest(FeatureSchema):
    patient_id: str = Field(min_length=1, max_length=100)
    observations: list[MetricObservation] = Field(default_factory=list)
    as_of_date: date | None = None
    config: FeaturePipelineConfig = Field(default_factory=FeaturePipelineConfig)


class TrendAssessment(FeatureSchema):
    trend: MetricTrend
    slope: float | None
    first_to_last_relative_change: float | None
    coefficient_of_variation: float | None
    direction_consistency: float | None
    reason: str


class EarlyWarningAssessment(FeatureSchema):
    status: EarlyWarningStatus
    reason: str | None


class MetricLongitudinalFeatures(FeatureSchema):
    metric_code: str
    canonical_name: str
    standard_unit: str | None
    feature_group: FeatureGroup
    current_value: float | None
    previous_value: float | None
    absolute_change: float | None
    relative_change: float | None
    mean: float | None
    std: float | None
    min: float | None
    max: float | None
    slope: float | None
    trend: MetricTrend
    current_abnormal: bool
    abnormal_count: int = Field(ge=0)
    consecutive_abnormal_count: int = Field(ge=0)
    distance_to_reference_upper: float | None
    distance_to_reference_lower: float | None
    early_warning: EarlyWarningStatus
    warning_reason: str | None
    observation_count: int = Field(ge=0)
    source_observation_count: int = Field(ge=0)
    missing_observation_count: int = Field(ge=0)
    has_history: bool
    first_to_last_relative_change: float | None
    coefficient_of_variation: float | None
    direction_consistency: float | None
    trend_reason: str
    evidence_refs: list[str]


class SystemFeatureGroup(FeatureSchema):
    metrics: dict[str, MetricLongitudinalFeatures] = Field(default_factory=dict)
    metric_count: int = Field(ge=0)
    currently_abnormal_metric_count: int = Field(ge=0)
    early_warning_metric_count: int = Field(ge=0)


FeatureValue = float | int | bool | None


class PatientFeatureVector(FeatureSchema):
    patient_id: str
    as_of_date: date | None
    feature_pipeline_version: str
    metric_features: dict[str, MetricLongitudinalFeatures]
    metabolic_features: SystemFeatureGroup
    cardiovascular_features: SystemFeatureGroup
    liver_features: SystemFeatureGroup
    kidney_features: SystemFeatureGroup
    other_features: SystemFeatureGroup
    feature_values: dict[str, FeatureValue]
    feature_order: list[str]
    evidence_refs: list[str]
