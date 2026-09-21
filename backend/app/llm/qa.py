"""档案问答服务（H08）：引用守卫与只读保证。

QAContext 是冻结的只读视图（记录、方案快照引用、证据条目）；服务
没有任何写方法——问答不能修改已保存方案。模型回答中的引用编号
（[EV:xxx]）必须存在于上下文，否则引用被标记无效并从正文中摘除，
不编造引用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.versioning import PipelineVersions
from app.llm.contracts import LLMResponse, PatientChatRequest, StructuredPatientContext
from app.llm.provider import LLMProvider

CITATION_RE = re.compile(r"\[EV:([A-Za-z0-9_\-\.]+)\]")
CITATION_MODE = "template"  # 占位；实际 mode 由 provider 类型决定


@dataclass(frozen=True)
class EvidenceItem:
    """证据条目：ref_id 即引用编号，text 是面向问答的受控描述。"""

    ref_id: str
    text: str
    record_ref: str


@dataclass(frozen=True)
class QAContext:
    """只读问答上下文：由 T10 从档案与方案快照构造。"""

    patient_ref: str
    findings: tuple[EvidenceItem, ...] = ()
    plan_snapshot_ref: str | None = None
    plan_summary: str | None = None
    versions: PipelineVersions = field(default_factory=PipelineVersions)

    def evidence_ids(self) -> frozenset[str]:
        return frozenset(item.ref_id for item in self.findings)


@dataclass
class QAAnswer:
    """问答输出：内容 + 引用核对结果 + 模式标注。"""

    question: str
    content: str
    mode: str  # "model" | "template"
    llm_model: str
    trace_id: str
    citations: tuple[str, ...]
    invalid_citations_removed: tuple[str, ...] = ()
    plan_snapshot_ref: str | None = None

    def as_dict(self) -> dict:
        return {
            "question": self.question,
            "content": self.content,
            "mode": self.mode,
            "llm_model": self.llm_model,
            "trace_id": self.trace_id,
            "citations": list(self.citations),
            "invalid_citations_removed": list(self.invalid_citations_removed),
            "plan_snapshot_ref": self.plan_snapshot_ref,
        }


class QAService:
    """H08 问答服务：只读上下文 + 引用守卫。"""

    VERSION = "qa-service-v1"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def answer(self, question: str, context: QAContext) -> QAAnswer:
        if not question.strip():
            raise ValueError("问题不能为空")
        request = PatientChatRequest(
            context=self._to_structured(context),
            user_message=question.strip(),
        )
        response = await self._provider.chat_with_patient_context(request)
        return self._finalize(question, response, context)

    # ---- 上下文转换 ----

    def _to_structured(self, context: QAContext) -> StructuredPatientContext:
        findings = [item.text for item in context.findings]
        if context.plan_summary:
            findings.append(f"当前方案快照 {context.plan_snapshot_ref}：{context.plan_summary}")
        return StructuredPatientContext(
            patient_id=context.patient_ref,
            normalized_findings=findings,
            evidence_refs=sorted(context.evidence_ids()),
            versions=context.versions,
        )

    # ---- 引用守卫 ----

    def _finalize(
        self, question: str, response: LLMResponse, context: QAContext
    ) -> QAAnswer:
        valid_ids = context.evidence_ids()
        cited = CITATION_RE.findall(response.content)
        invalid = [ref for ref in dict.fromkeys(cited) if ref not in valid_ids]
        content = response.content
        if invalid:
            for ref in invalid:
                content = content.replace(f"[EV:{ref}]", "")
            content = (
                content
                + "\n（注意：回答中出现的不在证据列表内的引用已被移除，请人工核对原始记录）"
            )
        return QAAnswer(
            question=question,
            content=content,
            mode="model" if response.llm_model != "local-template" else "template",
            llm_model=response.llm_model,
            trace_id=response.trace_id,
            citations=tuple(ref for ref in dict.fromkeys(cited) if ref in valid_ids),
            invalid_citations_removed=tuple(invalid),
            plan_snapshot_ref=context.plan_snapshot_ref,
        )
