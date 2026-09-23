from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    AIReportType,
    CostLevel,
    ExamResultStatus,
    Gender,
    MatchStatus,
    MetricStatus,
    NormalizationStatus,
    PlanTier,
    RecommendationDecision,
    RecommendationStatus,
    RuleAction,
    ValueType,
)
from app.rules.models import RuleType


class DomainSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ReadSchema(DomainSchema):
    id: str
    created_at: datetime


class PatientCreate(DomainSchema):
    anonymous_code: str = Field(min_length=1, max_length=64)
    gender: Gender = Gender.UNKNOWN
    birth_date: date | None = None
    height: float | None = Field(default=None, gt=0, le=300)

    @field_validator("anonymous_code")
    @classmethod
    def normalize_anonymous_code(cls, value: str) -> str:
        return value.strip().upper()


class PatientUpdate(DomainSchema):
    anonymous_code: str | None = Field(default=None, min_length=1, max_length=64)
    gender: Gender | None = None
    birth_date: date | None = None
    height: float | None = Field(default=None, gt=0, le=300)

    @field_validator("anonymous_code")
    @classmethod
    def normalize_anonymous_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class PatientRead(PatientCreate, ReadSchema):
    pass


class HealthCheckCreate(DomainSchema):
    patient_id: str
    check_date: date
    institution: str | None = Field(default=None, max_length=200)
    is_demo: bool = False
    source_kind: str = Field(default="manual", min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=200)


class HealthCheckUpdate(DomainSchema):
    patient_id: str | None = None
    check_date: date | None = None
    institution: str | None = Field(default=None, max_length=200)
    is_demo: bool | None = None
    source_kind: str | None = Field(default=None, min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=200)


class HealthCheckRead(HealthCheckCreate, ReadSchema):
    revision_no: int


class MetricDictionaryCreate(DomainSchema):
    metric_code: str = Field(min_length=1, max_length=64)
    canonical_name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list)
    standard_unit: str | None = Field(default=None, max_length=50)
    category: str = Field(min_length=1, max_length=100)
    value_type: ValueType = ValueType.NUMERIC
    unit_conversions: dict[str, dict[str, float]] = Field(default_factory=dict)
    valid_min: float | None = None
    valid_max: float | None = None
    source: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=64)

    @field_validator("metric_code")
    @classmethod
    def normalize_metric_code(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_range(self) -> "MetricDictionaryCreate":
        if self.valid_min is not None and self.valid_max is not None:
            if self.valid_min > self.valid_max:
                raise ValueError("valid_min must not exceed valid_max")
        return self


class MetricDictionaryUpdate(DomainSchema):
    metric_code: str | None = Field(default=None, min_length=1, max_length=64)
    canonical_name: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    standard_unit: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    value_type: ValueType | None = None
    unit_conversions: dict[str, dict[str, float]] | None = None
    valid_min: float | None = None
    valid_max: float | None = None
    source: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("metric_code")
    @classmethod
    def normalize_metric_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class MetricDictionaryRead(MetricDictionaryCreate, ReadSchema):
    pass


class LabMetricCreate(DomainSchema):
    health_check_id: str
    metric_code: str = Field(min_length=1, max_length=64)
    original_name: str = Field(min_length=1, max_length=200)
    canonical_name: str = Field(min_length=1, max_length=200)
    original_value: str = Field(min_length=1, max_length=100)
    value: float | None = None
    original_unit: str | None = Field(default=None, max_length=50)
    standard_unit: str | None = Field(default=None, max_length=50)
    reference_min: float | None = None
    reference_max: float | None = None
    status: MetricStatus = MetricStatus.UNKNOWN
    normalization_status: NormalizationStatus
    normalization_version: str = Field(min_length=1, max_length=64)
    value_type: ValueType = ValueType.NUMERIC
    qualitative_value: str | None = Field(default=None, max_length=100)
    source_kind: str = Field(default="manual", min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=200)

    @field_validator("metric_code")
    @classmethod
    def normalize_metric_code(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_reference_range(self) -> "LabMetricCreate":
        if self.reference_min is not None and self.reference_max is not None:
            if self.reference_min > self.reference_max:
                raise ValueError("reference_min must not exceed reference_max")
        if self.value_type is ValueType.QUALITATIVE and not (self.qualitative_value or "").strip():
            raise ValueError("定性结果必须填写 qualitative_value，不能只留空值")
        if self.value_type is ValueType.NUMERIC and self.qualitative_value:
            raise ValueError("数值型指标不能同时填写 qualitative_value，请明确纠正或换算")
        return self


class LabMetricUpdate(DomainSchema):
    health_check_id: str | None = None
    metric_code: str | None = Field(default=None, min_length=1, max_length=64)
    original_name: str | None = Field(default=None, min_length=1, max_length=200)
    canonical_name: str | None = Field(default=None, min_length=1, max_length=200)
    original_value: str | None = Field(default=None, min_length=1, max_length=100)
    value: float | None = None
    original_unit: str | None = Field(default=None, max_length=50)
    standard_unit: str | None = Field(default=None, max_length=50)
    reference_min: float | None = None
    reference_max: float | None = None
    status: MetricStatus | None = None
    normalization_status: NormalizationStatus | None = None
    normalization_version: str | None = Field(default=None, min_length=1, max_length=64)
    value_type: ValueType | None = None
    qualitative_value: str | None = Field(default=None, max_length=100)
    source_kind: str | None = Field(default=None, min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=200)

    @field_validator("metric_code")
    @classmethod
    def normalize_metric_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class LabMetricRead(LabMetricCreate, ReadSchema):
    revision_no: int


class ImagingExamCreate(DomainSchema):
    health_check_id: str
    exam_type: str = Field(min_length=1, max_length=100)
    body_part: str = Field(min_length=1, max_length=100)
    report_text: str | None = None
    exam_date: date
    source_kind: str = Field(default="manual", min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=200)


class ImagingExamUpdate(DomainSchema):
    health_check_id: str | None = None
    exam_type: str | None = Field(default=None, min_length=1, max_length=100)
    body_part: str | None = Field(default=None, min_length=1, max_length=100)
    report_text: str | None = None
    exam_date: date | None = None
    source_kind: str | None = Field(default=None, min_length=1, max_length=32)
    source_ref: str | None = Field(default=None, max_length=200)


class ImagingExamRead(ImagingExamCreate, ReadSchema):
    revision_no: int


class LesionCreate(DomainSchema):
    imaging_exam_id: str
    lesion_type: str = Field(min_length=1, max_length=100)
    original_location: str = Field(min_length=1, max_length=200)
    location: str = Field(min_length=1, max_length=100)
    size_mm: float | None = Field(default=None, ge=0)
    grade: str | None = Field(default=None, max_length=100)
    description: str | None = None


class LesionUpdate(DomainSchema):
    imaging_exam_id: str | None = None
    lesion_type: str | None = Field(default=None, min_length=1, max_length=100)
    original_location: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, min_length=1, max_length=100)
    size_mm: float | None = Field(default=None, ge=0)
    grade: str | None = Field(default=None, max_length=100)
    description: str | None = None


class LesionRead(LesionCreate, ReadSchema):
    pass


class LesionTrackCreate(DomainSchema):
    patient_id: str
    canonical_lesion_id: str = Field(min_length=1, max_length=100)
    lesion_type: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=100)
    first_seen: date
    last_seen: date

    @model_validator(mode="after")
    def validate_dates(self) -> "LesionTrackCreate":
        if self.first_seen > self.last_seen:
            raise ValueError("first_seen must not exceed last_seen")
        return self


class LesionTrackUpdate(DomainSchema):
    patient_id: str | None = None
    canonical_lesion_id: str | None = Field(default=None, min_length=1, max_length=100)
    lesion_type: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, min_length=1, max_length=100)
    first_seen: date | None = None
    last_seen: date | None = None


class LesionTrackRead(LesionTrackCreate, ReadSchema):
    pass


class LesionObservationCreate(DomainSchema):
    lesion_track_id: str
    lesion_id: str
    exam_date: date
    size_mm: float | None = Field(default=None, ge=0)
    grade: str | None = Field(default=None, max_length=100)
    match_confidence: float = Field(ge=0, le=1)
    match_status: MatchStatus


class LesionObservationUpdate(DomainSchema):
    lesion_track_id: str | None = None
    lesion_id: str | None = None
    exam_date: date | None = None
    size_mm: float | None = Field(default=None, ge=0)
    grade: str | None = Field(default=None, max_length=100)
    match_confidence: float | None = Field(default=None, ge=0, le=1)
    match_status: MatchStatus | None = None


class LesionObservationRead(LesionObservationCreate, ReadSchema):
    pass


class ExamItemCreate(DomainSchema):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str | None = None
    radiation: bool = False
    cost_level: CostLevel
    recommended_interval_months: int | None = Field(default=None, gt=0)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


class ExamItemUpdate(DomainSchema):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    radiation: bool | None = None
    cost_level: CostLevel | None = None
    recommended_interval_months: int | None = Field(default=None, gt=0)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None


class ExamItemRead(ExamItemCreate, ReadSchema):
    pass


class ExamHistoryCreate(DomainSchema):
    health_check_id: str
    exam_item_id: str
    result_status: ExamResultStatus


class ExamHistoryUpdate(DomainSchema):
    health_check_id: str | None = None
    exam_item_id: str | None = None
    result_status: ExamResultStatus | None = None


class ExamHistoryRead(ExamHistoryCreate, ReadSchema):
    pass


class MedicalRuleCreate(DomainSchema):
    rule_code: str = Field(min_length=1, max_length=100)
    rule_type: RuleType
    exam_item_id: str | None = None
    condition_json: dict[str, Any]
    action: RuleAction
    priority: int = Field(default=0, ge=0)
    source: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=64)
    enabled: bool = True

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("rule source must not be blank")
        return value


class MedicalRuleUpdate(DomainSchema):
    rule_code: str | None = Field(default=None, min_length=1, max_length=100)
    rule_type: RuleType | None = None
    exam_item_id: str | None = None
    condition_json: dict[str, Any] | None = None
    action: RuleAction | None = None
    priority: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, min_length=1, max_length=300)
    version: str | None = Field(default=None, min_length=1, max_length=64)
    enabled: bool | None = None

    @field_validator("source")
    @classmethod
    def validate_optional_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("rule source must not be blank")
        return value


class MedicalRuleRead(MedicalRuleCreate, ReadSchema):
    pass


class RiskPredictionCreate(DomainSchema):
    patient_id: str
    as_of_health_check_id: str | None = None
    risk_code: str = Field(min_length=1, max_length=100)
    probability: float = Field(ge=0, le=1)
    risk_level: str | None = Field(default=None, max_length=50)
    feature_pipeline_version: str = Field(min_length=1, max_length=64)
    risk_model_version: str = Field(min_length=1, max_length=64)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str = Field(min_length=1, max_length=100)
    is_demo: bool = False


class RiskPredictionUpdate(DomainSchema):
    patient_id: str | None = None
    as_of_health_check_id: str | None = None
    risk_code: str | None = Field(default=None, min_length=1, max_length=100)
    probability: float | None = Field(default=None, ge=0, le=1)
    risk_level: str | None = Field(default=None, max_length=50)
    feature_pipeline_version: str | None = Field(default=None, min_length=1, max_length=64)
    risk_model_version: str | None = Field(default=None, min_length=1, max_length=64)
    evidence_refs: list[dict[str, Any]] | None = None
    trace_id: str | None = Field(default=None, min_length=1, max_length=100)
    is_demo: bool | None = None


class RiskPredictionRead(RiskPredictionCreate, ReadSchema):
    pass


class RecommendationCreate(DomainSchema):
    patient_id: str
    as_of_health_check_id: str | None = None
    plan_tier: PlanTier
    status: RecommendationStatus = RecommendationStatus.DRAFT
    feature_pipeline_version: str | None = Field(default=None, max_length=64)
    risk_model_version: str | None = Field(default=None, max_length=64)
    recommendation_model_version: str | None = Field(default=None, max_length=64)
    rule_version: str | None = Field(default=None, max_length=64)
    trace_id: str = Field(min_length=1, max_length=100)
    is_demo: bool = False


class RecommendationUpdate(DomainSchema):
    patient_id: str | None = None
    as_of_health_check_id: str | None = None
    plan_tier: PlanTier | None = None
    status: RecommendationStatus | None = None
    feature_pipeline_version: str | None = Field(default=None, max_length=64)
    risk_model_version: str | None = Field(default=None, max_length=64)
    recommendation_model_version: str | None = Field(default=None, max_length=64)
    rule_version: str | None = Field(default=None, max_length=64)
    trace_id: str | None = Field(default=None, min_length=1, max_length=100)
    is_demo: bool | None = None


class RecommendationRead(RecommendationCreate, ReadSchema):
    pass


class RecommendationItemCreate(DomainSchema):
    recommendation_id: str
    exam_item_id: str
    model_score: float | None = Field(default=None, ge=0, le=1)
    final_score: float | None = Field(default=None, ge=0, le=1)
    decision: RecommendationDecision
    rank: int | None = Field(default=None, gt=0)
    explanation: str | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    applied_rules: list[dict[str, Any]] = Field(default_factory=list)


class RecommendationItemUpdate(DomainSchema):
    recommendation_id: str | None = None
    exam_item_id: str | None = None
    model_score: float | None = Field(default=None, ge=0, le=1)
    final_score: float | None = Field(default=None, ge=0, le=1)
    decision: RecommendationDecision | None = None
    rank: int | None = Field(default=None, gt=0)
    explanation: str | None = None
    evidence_refs: list[dict[str, Any]] | None = None
    applied_rules: list[dict[str, Any]] | None = None


class RecommendationItemRead(RecommendationItemCreate, ReadSchema):
    pass


class AIReportCreate(DomainSchema):
    patient_id: str
    recommendation_id: str | None = None
    report_type: AIReportType
    content: str = Field(min_length=1)
    llm_model: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=64)
    source_trace_id: str = Field(min_length=1, max_length=100)
    is_demo: bool = False


class AIReportUpdate(DomainSchema):
    patient_id: str | None = None
    recommendation_id: str | None = None
    report_type: AIReportType | None = None
    content: str | None = Field(default=None, min_length=1)
    llm_model: str | None = Field(default=None, min_length=1, max_length=100)
    prompt_version: str | None = Field(default=None, min_length=1, max_length=64)
    source_trace_id: str | None = Field(default=None, min_length=1, max_length=100)
    is_demo: bool | None = None


class AIReportRead(AIReportCreate, ReadSchema):
    pass


class MetricNormalizationRequest(DomainSchema):
    original_name: str = Field(min_length=1, max_length=200)
    original_value: str = Field(min_length=1, max_length=100)
    original_unit: str | None = Field(default=None, max_length=50)
    reference_min: float | None = None
    reference_max: float | None = None


class MetricNormalizationResult(DomainSchema):
    metric_code: str | None
    canonical_name: str | None
    original_name: str
    original_value: str
    value: float | None
    original_unit: str | None
    standard_unit: str | None
    reference_min: float | None
    reference_max: float | None
    status: MetricStatus
    normalization_status: NormalizationStatus
    normalization_version: str
    issues: list[str] = Field(default_factory=list)


class LesionTerminologyRequest(DomainSchema):
    location: str = Field(min_length=1, max_length=200)


class LesionTerminologyResult(DomainSchema):
    original_location: str
    canonical_location: str | None
    matched: bool
    terminology_version: str
