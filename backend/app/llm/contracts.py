from pydantic import BaseModel, ConfigDict, Field

from app.core.versioning import PipelineVersions


class StructuredPatientContext(BaseModel):
    """允许传给 LLM 的受控上下文；禁止放入原始体检报告全文。"""

    model_config = ConfigDict(frozen=True)

    patient_id: str
    normalized_findings: list[str] = Field(default_factory=list)
    trend_summaries: list[str] = Field(default_factory=list)
    risk_summaries: list[str] = Field(default_factory=list)
    recommendation_summaries: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    versions: PipelineVersions = Field(default_factory=PipelineVersions)


class HealthSummaryRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: StructuredPatientContext


class RecommendationExplanationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: StructuredPatientContext
    recommendation_id: str


class PatientChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    context: StructuredPatientContext
    user_message: str = Field(min_length=1, max_length=4000)


class LLMResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    llm_model: str
    trace_id: str
