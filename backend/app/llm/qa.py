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
from app.llm.citations import (
    CitationBinding,
    extract_inline_citations,
    validate_citations,
)
from app.llm.contracts import (
    EvidenceItem as StructuredEvidenceItem,
    LLMResponse,
    PatientChatRequest,
    StructuredPatientContext,
)
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

    def evidence_by_id(self) -> dict[str, EvidenceItem]:
        return {item.ref_id: item for item in self.findings}

    def record_ref_for(self, ref_id: str) -> str | None:
        item = self.evidence_by_id().get(ref_id)
        return item.record_ref if item else None

    def citation_bindings(self) -> list[CitationBinding]:
        """折算成共享校验链路使用的绑定结构（与 T10 同一入口）。"""
        return [
            CitationBinding(ref_id=i.ref_id, text=i.text, record_ref=i.record_ref)
            for i in self.findings
        ]


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
    citation_records: tuple[tuple[str, str], ...] = ()

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
            "citation_records": [list(pair) for pair in self.citation_records],
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
        """把只读上下文转成模型上下文：编号与正文**成对**下发。

        PR #26 P1：旧实现只发 text 列表并把 evidence_refs 单独排序，
        两处顺序不一致时模型无法判断哪段文字对应哪个编号，守卫也只
        检查编号存在性。改为逐条绑定 (ref_id, text, record_ref)。
        """
        findings = [item.text for item in context.findings]
        if context.plan_summary:
            findings.append(f"当前方案快照 {context.plan_snapshot_ref}：{context.plan_summary}")
        evidence_items = [
            StructuredEvidenceItem(
                ref_id=item.ref_id,
                text=item.text,
                record_ref=item.record_ref,
            )
            for item in context.findings
        ]
        return StructuredPatientContext(
            patient_id=context.patient_ref,
            normalized_findings=findings,
            evidence_refs=[item.ref_id for item in context.findings],
            evidence_items=evidence_items,
            versions=context.versions,
        )

    # ---- 引用守卫 ----

    def _finalize(
        self, question: str, response: LLMResponse, context: QAContext
    ) -> QAAnswer:
        """引用守卫：走共享校验链路（与 T10 判定口径一致）。"""
        bindings = context.citation_bindings()
        cited = extract_inline_citations(response.content)
        verdict = validate_citations(cited, bindings, content=response.content)
        invalid = verdict.rejected
        by_id = context.evidence_by_id()

        content = response.content
        if invalid:
            for ref in invalid:
                content = content.replace(f"[EV:{ref}]", "")
            content = (
                content
                + "\n（注意：回答中出现的不在证据列表内或与所引编号不匹配的引用已被移除，"
                "请人工核对原始记录）"
            )
        citations = tuple(verdict.accepted)
        return QAAnswer(
            question=question,
            content=content,
            mode="model" if response.llm_model != "local-template" else "template",
            llm_model=response.llm_model,
            trace_id=response.trace_id,
            citations=citations,
            invalid_citations_removed=tuple(invalid),
            plan_snapshot_ref=context.plan_snapshot_ref,
            citation_records=tuple(
                (ref, by_id[ref].record_ref) for ref in citations if ref in by_id
            ),
        )
