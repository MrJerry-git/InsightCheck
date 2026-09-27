from pydantic import BaseModel, ConfigDict, Field

from app.core.versioning import PipelineVersions


class EvidenceItem(BaseModel):
    """受控证据条目：编号与文本**成对**下发。

    编号与正文分开下发会导致模型无法判断哪段文字对应哪个 [EV:...]，
    引用守卫只能检查编号存在性，从而接受「引用到错误记录」的回答
    （PR #26 P1）。这里强制三者绑定并一起进入模型上下文。
    """

    model_config = ConfigDict(frozen=True)

    ref_id: str = Field(min_length=1)
    text: str
    record_ref: str


class StructuredPatientContext(BaseModel):
    """允许传给 LLM 的受控上下文；禁止放入原始体检报告全文。"""

    model_config = ConfigDict(frozen=True)

    patient_id: str
    normalized_findings: list[str] = Field(default_factory=list)
    trend_summaries: list[str] = Field(default_factory=list)
    risk_summaries: list[str] = Field(default_factory=list)
    recommendation_summaries: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    versions: PipelineVersions = Field(default_factory=PipelineVersions)

    def evidence_pairs(self) -> list[tuple[str, str, str]]:
        """(ref_id, text, record_ref) 三元组列表，供提示词组装。

        以 evidence_items 为准；若只给了 evidence_refs（未绑定正文），
        退回按编号占位，绝不臆造配对关系。
        """
        if self.evidence_items:
            return [(i.ref_id, i.text, i.record_ref) for i in self.evidence_items]
        return [(ref, "", "") for ref in self.evidence_refs]

    def format_evidence_block(self) -> str:
        """把编号/正文/记录来源成对排成受控清单。"""
        pairs = self.evidence_pairs()
        if not pairs:
            return "（无证据条目）"
        return "\n".join(
            f"[EV:{ref_id}] {text}（来源记录：{record_ref or '未标注'}）"
            for ref_id, text, record_ref in pairs
        )

    def citation_catalog(self) -> list[dict[str, str]]:
        """T10（feat/report-qa）`citations` 形态的等价投影。

        T10 的 QaService 用 `{"type": "ref", "label"}` 三元组描述可用引用，
        模型被要求返回 `{"answer": ..., "citations": [{"ref": ...}]}`。
        H08 用 `[EV:<ref_id>]` 行内标注。两者只是**同一套引用集合的不同表示**，
        这里给出可互相转换的投影，避免两条链路各自维护一套校验逻辑。
        """
        return [
            {
                "type": "evidence",
                "ref": ref_id,
                "label": text,
                "record_ref": record_ref,
            }
            for ref_id, text, record_ref in self.evidence_pairs()
        ]


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
