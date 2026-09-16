from datetime import date
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RuleType(StrEnum):
    INTERVAL = "INTERVAL"
    DUPLICATE = "DUPLICATE"
    RADIATION = "RADIATION"
    AGE = "AGE"
    GENDER = "GENDER"
    RISK = "RISK"
    LESION_FOLLOWUP = "LESION_FOLLOWUP"
    MISSING_DATA = "MISSING_DATA"


class RuleAction(StrEnum):
    ALLOW = "ALLOW"
    BOOST = "BOOST"
    REDUCE = "REDUCE"
    DEFER = "DEFER"
    BLOCK = "BLOCK"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class FinalRuleStatus(StrEnum):
    ALLOWED = "ALLOWED"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class PatientContext(BaseModel):
    """规则所需的最小结构化受检者上下文，不接收身份信息或报告正文。"""

    model_config = ConfigDict(frozen=True)

    patient_id: str = Field(min_length=1)
    as_of_date: date
    age: int | None = Field(default=None, ge=0, le=130)
    sex: Literal["female", "male", "other", "unknown"] = "unknown"
    normalized_facts: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class CandidateExamItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    exam_item_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    body_part: str | None = None
    radiation: bool = False
    functional_groups: list[str] = Field(default_factory=list)
    recommended_interval_months: int | None = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ExamHistoryFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    exam_item_id: str = Field(min_length=1)
    exam_code: str = Field(min_length=1)
    performed_at: date
    result_status: str = Field(min_length=1)
    category: str | None = None
    body_part: str | None = None
    radiation: bool = False
    functional_groups: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class RiskPredictionFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    risk_code: str = Field(min_length=1)
    probability: float = Field(ge=0, le=1)
    model_version: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class LesionHistoryFact(BaseModel):
    model_config = ConfigDict(frozen=True)

    lesion_type: str = Field(min_length=1)
    location: str | None = None
    last_exam_date: date
    match_status: str
    growing: bool | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class MedicalRuleDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_code: str = Field(min_length=1, max_length=100)
    rule_type: RuleType
    exam_item_id: str | None = None
    condition: dict[str, Any]
    action: RuleAction
    priority: int = Field(default=0, ge=0)
    source: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=64)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_score_adjustment(self) -> "MedicalRuleDefinition":
        score_delta = self.condition.get("score_delta")
        if self.action in {RuleAction.BOOST, RuleAction.REDUCE}:
            if not isinstance(score_delta, int | float) or score_delta <= 0:
                raise ValueError("BOOST/REDUCE rule requires a positive condition.score_delta")
        return self


class RuleEvaluationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    patient: PatientContext
    exam_item: CandidateExamItem
    deepfm_score: float = Field(ge=0, le=1)
    risk_predictions: list[RiskPredictionFact] = Field(default_factory=list)
    exam_history: list[ExamHistoryFact] = Field(default_factory=list)
    lesion_history: list[LesionHistoryFact] = Field(default_factory=list)
    selected_exam_items: list[CandidateExamItem] = Field(default_factory=list)
    trace_id: str = Field(min_length=1)


class RuleDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_code: str
    rule_type: RuleType
    action: RuleAction
    reason: str = Field(min_length=1)
    source: str = Field(min_length=1)
    version: str = Field(min_length=1)
    priority: int = Field(ge=0)
    score_delta: float = 0.0
    evidence_refs: list[str] = Field(default_factory=list)


class RuleExecutionRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_code: str
    version: str
    priority: int
    enabled: bool
    matched: bool
    action: RuleAction | None = None
    reason: str
    score_before: float
    score_after: float


class RuleEvaluationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace_id: str
    deepfm_score: float = Field(ge=0, le=1)
    adjusted_score: float = Field(ge=0, le=1)
    final_status: FinalRuleStatus
    rule_decisions: list[RuleDecision]
    execution_trace: list[RuleExecutionRecord]
    rule_set_version: str
