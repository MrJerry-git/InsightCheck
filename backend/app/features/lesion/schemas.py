from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LesionFeatureSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LesionTerminologyResult(LesionFeatureSchema):
    original_location: str
    canonical_location: str | None
    matched: bool
    terminology_version: str


class LesionMatchStatus(StrEnum):
    MATCHED = "MATCHED"
    NEED_REVIEW = "NEED_REVIEW"
    NEW_LESION = "NEW_LESION"


class TrackPresenceStatus(StrEnum):
    CONTINUING = "CONTINUING"
    DISAPPEARED = "DISAPPEARED"
    UNRESOLVED = "UNRESOLVED"


class MatchingWeights(LesionFeatureSchema):
    lesion_type: float = Field(default=0.35, ge=0, le=1)
    organ: float = Field(default=0.20, ge=0, le=1)
    location: float = Field(default=0.20, ge=0, le=1)
    size: float = Field(default=0.15, ge=0, le=1)
    grade: float = Field(default=0.10, ge=0, le=1)

    @model_validator(mode="after")
    def validate_total(self) -> "MatchingWeights":
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("病灶匹配权重之和必须为 1")
        return self


class LesionMatchingConfig(LesionFeatureSchema):
    version: str = "lesion-matching-v1"
    weights: MatchingWeights = Field(default_factory=MatchingWeights)
    matched_threshold: float = Field(default=0.80, ge=0, le=1)
    review_threshold: float = Field(default=0.55, ge=0, le=1)
    size_relative_change_for_zero_score: float = Field(default=0.50, gt=0)
    extreme_size_relative_change: float = Field(default=1.00, gt=0)
    conflict_confidence_cap: float = Field(default=0.79, ge=0, le=1)
    missing_location_confidence_cap: float = Field(default=0.79, ge=0, le=1)
    max_supported_interval_months: float = Field(default=24.0, gt=0)
    long_interval_multiplier: float = Field(default=0.90, gt=0, le=1)
    max_disappearance_interval_months: float = Field(default=24.0, gt=0)

    @model_validator(mode="after")
    def validate_thresholds(self) -> "LesionMatchingConfig":
        if self.review_threshold >= self.matched_threshold:
            raise ValueError("review_threshold 必须小于 matched_threshold")
        if self.conflict_confidence_cap >= self.matched_threshold:
            raise ValueError("冲突置信度上限必须低于自动匹配阈值")
        if self.missing_location_confidence_cap >= self.matched_threshold:
            raise ValueError("缺失位置置信度上限必须低于自动匹配阈值")
        return self


class StructuredLesion(LesionFeatureSchema):
    lesion_id: str = Field(min_length=1, max_length=100)
    exam_date: date
    lesion_type: str = Field(min_length=1, max_length=100)
    organ: str | None = Field(default=None, max_length=100)
    body_part: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=200)
    size_mm: float | None = Field(default=None, ge=0)
    grade: str | None = Field(default=None, max_length=100)


class LesionTrackCandidate(LesionFeatureSchema):
    track_id: str = Field(min_length=1, max_length=100)
    observations: list[StructuredLesion] = Field(min_length=1)


class LesionMatchingRequest(LesionFeatureSchema):
    current_exam_date: date
    previous_tracks: list[LesionTrackCandidate] = Field(default_factory=list)
    current_lesions: list[StructuredLesion] = Field(default_factory=list)
    complete_body_parts: list[str] = Field(default_factory=list)
    config: LesionMatchingConfig = Field(default_factory=LesionMatchingConfig)


class LesionPairScore(LesionFeatureSchema):
    current_lesion_id: str
    candidate_track_id: str
    confidence: float = Field(ge=0, le=1)
    component_scores: dict[str, float]
    weighted_contributions: dict[str, float]
    reasons: list[str]


class LesionMatchDecision(LesionFeatureSchema):
    current_lesion_id: str
    candidate_track_id: str | None = None
    matched_track_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: LesionMatchStatus
    component_scores: dict[str, float] = Field(default_factory=dict)
    weighted_contributions: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class TrackPresenceDecision(LesionFeatureSchema):
    track_id: str
    status: TrackPresenceStatus
    disappeared: bool
    reasons: list[str] = Field(default_factory=list)


class LesionMatchingResult(LesionFeatureSchema):
    matches: list[LesionMatchDecision]
    track_presence: list[TrackPresenceDecision]
    matching_version: str


class GradeChange(StrEnum):
    UNCHANGED = "UNCHANGED"
    INCREASED = "INCREASED"
    DECREASED = "DECREASED"
    CHANGED = "CHANGED"
    UNKNOWN = "UNKNOWN"


class LesionTrendConfig(LesionFeatureSchema):
    version: str = "lesion-trend-v1"
    stable_absolute_change_mm: float = Field(default=0.50, ge=0)
    stable_relative_change: float = Field(default=0.10, ge=0)
    max_continuous_gap_months: float = Field(default=18.0, gt=0)
    months_per_year: float = Field(default=12.0, gt=0)
    grade_order: dict[str, int] = Field(
        default_factory=lambda: {"G1": 1, "G2": 2, "G3": 3, "G4": 4, "G5": 5}
    )


class LesionTrendRequest(LesionFeatureSchema):
    track_id: str = Field(min_length=1, max_length=100)
    observations: list[StructuredLesion] = Field(min_length=1)
    evaluation_date: date
    initial_match_status: LesionMatchStatus
    presence_status: TrackPresenceStatus
    config: LesionTrendConfig = Field(default_factory=LesionTrendConfig)


class LesionTrendPoint(LesionFeatureSchema):
    lesion_id: str
    exam_date: date
    size_mm: float | None
    grade: str | None
    absolute_change_from_previous: float | None
    months_from_previous: float | None


class LesionTrendResult(LesionFeatureSchema):
    track_id: str
    observations: list[LesionTrendPoint]
    absolute_size_change: float | None
    relative_size_change: float | None
    growth_rate: float | None
    grade_change: GradeChange
    continuous_occurrences: int = Field(ge=1)
    months_since_last_exam: float = Field(ge=0)
    new_lesion: bool
    disappeared: bool
    stable: bool
    growing: bool
    shrinking: bool
    reasons: list[str]
    trend_version: str


class LesionDemoAnalysisResult(LesionFeatureSchema):
    is_demo: bool
    demo_label: str
    patient_code: str
    track_id: str
    canonical_location: str
    matches: list[LesionMatchDecision]
    trend: LesionTrendResult
    disclaimer: str
