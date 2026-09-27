"""H08 问答服务：模板模式、OpenAI 兼容适配器与引用守卫。

异步接口用 asyncio.run() 驱动，不引入新的测试依赖。
"""

import asyncio

import pytest

from app.llm.citations import (
    CitationBinding,
    extract_inline_citations,
    validate_citations,
)
from app.llm.contracts import (
    EvidenceItem as StructuredEvidenceItem,
    HealthSummaryRequest,
    LLMResponse,
    PatientChatRequest,
    StructuredPatientContext,
)
from app.llm.openai_compat import LLMProviderError, OpenAICompatConfig, OpenAICompatibleLLMProvider
from app.llm.provider import LLMProvider
from app.llm.qa import EvidenceItem, QAContext, QAService
from app.llm.templated import TemplatedLLMProvider

# ---- 模板实现 ----


def make_context(**overrides) -> StructuredPatientContext:
    fields = {
        "patient_id": "P-001",
        "normalized_findings": ["空腹血糖 7.2 mmol/L（偏高）"],
        "trend_summaries": ["BMI 3 年 RISING"],
        "evidence_refs": ["EV-1", "EV-2"],
    }
    fields.update(overrides)
    return StructuredPatientContext(**fields)


def test_templated_provider_is_deterministic_and_labeled() -> None:
    provider = TemplatedLLMProvider()
    request = HealthSummaryRequest(context=make_context())
    first = asyncio.run(provider.generate_health_summary(request))
    second = asyncio.run(provider.generate_health_summary(request))
    assert first.content == second.content
    assert first.llm_model == "local-template"
    assert "模板" in first.content and "7.2" in first.content


def test_templated_chat_cites_evidence() -> None:
    provider = TemplatedLLMProvider()
    response = asyncio.run(
        provider.chat_with_patient_context(
            PatientChatRequest(context=make_context(), user_message="我的血糖怎么样？")
        )
    )
    assert isinstance(response, LLMResponse)
    assert "EV-1" in response.content


# ---- OpenAI 兼容适配器 ----


def test_unconfigured_provider_is_unavailable() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatConfig(base_url="", api_key="", model="")
    )
    assert provider.is_available() is False


def test_provider_failures_are_explicit_not_fabricated() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatConfig(base_url="https://api.example.invalid/v1", api_key="sk-x", model="m")
    )
    # 网络不可达/超时等都被转为 LLMProviderError，不编造内容
    with pytest.raises(LLMProviderError):
        asyncio.run(
            provider.chat_with_patient_context(
                PatientChatRequest(context=make_context(), user_message="问题")
            )
        )


def test_https_enforced() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatConfig(base_url="http://api.example.com/v1", api_key="k", model="m")
    )
    with pytest.raises(LLMProviderError) as excinfo:
        asyncio.run(
            provider.chat_with_patient_context(
                PatientChatRequest(context=make_context(), user_message="问题")
            )
        )
    assert "HTTPS" in str(excinfo.value)


def test_unconfigured_call_raises_configuration_error() -> None:
    provider = OpenAICompatibleLLMProvider(
        OpenAICompatConfig(base_url="", api_key="", model="")
    )
    with pytest.raises(LLMProviderError) as excinfo:
        asyncio.run(
            provider.chat_with_patient_context(
                PatientChatRequest(context=make_context(), user_message="问题")
            )
        )
    assert "未配置" in str(excinfo.value)


# ---- QAService 引用守卫 ----


def fake_provider(content: str, model: str = "fake-model") -> LLMProvider:
    class FakeProvider(LLMProvider):
        async def generate_health_summary(self, request):
            return LLMResponse(content="x", llm_model=model, trace_id="t")

        async def explain_recommendation(self, request):
            return LLMResponse(content="x", llm_model=model, trace_id="t")

        async def chat_with_patient_context(self, request):
            return LLMResponse(content=content, llm_model=model, trace_id="t")

    return FakeProvider()


def build_qa_context() -> QAContext:
    return QAContext(
        patient_ref="P-001",
        findings=(
            EvidenceItem(ref_id="EV-1", text="空腹血糖 7.2 mmol/L（偏高）", record_ref="rec-1"),
            EvidenceItem(ref_id="EV-2", text="尿酸 480 μmol/L（偏高）", record_ref="rec-2"),
        ),
        plan_snapshot_ref="snapshot-7",
        plan_summary="标准档方案 v1",
    )


def test_valid_citations_pass_guard() -> None:
    service = QAService(fake_provider("血糖偏高 [EV:EV-1]，尿酸偏高 [EV:EV-2]。"))
    answer = asyncio.run(service.answer("我的情况如何？", build_qa_context()))
    assert answer.mode == "model"
    assert answer.citations == ("EV-1", "EV-2")
    assert answer.invalid_citations_removed == ()
    assert answer.plan_snapshot_ref == "snapshot-7"


def test_fabricated_citations_removed_not_trusted() -> None:
    service = QAService(
        fake_provider("结论 [EV:EV-9] 与 [EV:EV-1]；[EV:EV-9] 不存在。")
    )
    answer = asyncio.run(service.answer("靠谱吗？", build_qa_context()))
    assert answer.invalid_citations_removed == ("EV-9",)
    assert answer.citations == ("EV-1",)
    assert "[EV:EV-9]" not in answer.content
    assert "人工核对" in answer.content


def test_template_mode_labeled_and_context_frozen() -> None:
    service = QAService(TemplatedLLMProvider())
    answer = asyncio.run(service.answer("解释一下", build_qa_context()))
    assert answer.mode == "template"
    # 只读保证：上下文为 frozen 数据类，篡改会被拒绝
    context = build_qa_context()
    with pytest.raises((AttributeError, TypeError)):
        context.plan_summary = "篡改"  # type: ignore[misc]


def test_empty_question_rejected() -> None:
    service = QAService(TemplatedLLMProvider())
    with pytest.raises(ValueError):
        asyncio.run(service.answer("  ", build_qa_context()))


def test_qa_service_has_no_write_surface() -> None:
    """只读保证：服务不提供任何写入/修改方案的方法。"""
    service = QAService(TemplatedLLMProvider())
    public = [name for name in dir(service) if not name.startswith("_")]
    assert set(public) <= {"VERSION", "answer"}


# ---- 引用绑定：编号与正文成对下发（PR #26 P1） ----


def capturing_provider() -> tuple[LLMProvider, list]:
    """记录下发给 provider 的请求，供断言上下文绑定关系。"""
    captured: list = []

    class CaptureProvider(LLMProvider):
        async def generate_health_summary(self, request):
            return LLMResponse(content="x", llm_model="fake-model", trace_id="t")

        async def explain_recommendation(self, request):
            return LLMResponse(content="x", llm_model="fake-model", trace_id="t")

        async def chat_with_patient_context(self, request):
            captured.append(request)
            return LLMResponse(
                content="血糖偏高 [EV:EV-1]，尿酸偏高 [EV:EV-2]。",
                llm_model="fake-model",
                trace_id="t",
            )

    return CaptureProvider(), captured


def test_evidence_pairs_are_bound_in_model_context() -> None:
    """审查复现：编号与正文必须成对下发，record_ref 不得丢失。"""
    provider, captured = capturing_provider()
    service = QAService(provider)
    asyncio.run(service.answer("我的情况如何？", build_qa_context()))

    context = captured[0].context
    pairs = context.evidence_pairs()
    assert pairs == [
        ("EV-1", "空腹血糖 7.2 mmol/L（偏高）", "rec-1"),
        ("EV-2", "尿酸 480 μmol/L（偏高）", "rec-2"),
    ], "编号/正文/来源记录必须逐条绑定"
    block = context.format_evidence_block()
    assert "[EV:EV-1] 空腹血糖 7.2 mmol/L（偏高）（来源记录：rec-1）" in block
    assert "rec-2" in block


def test_evidence_binding_survives_shuffled_input_order() -> None:
    """输入顺序与编号排序不同时，绑定关系不得错位。"""
    shuffled = QAContext(
        patient_ref="P-001",
        findings=(
            EvidenceItem(ref_id="EV-9", text="尿酸 480 μmol/L（偏高）", record_ref="rec-b"),
            EvidenceItem(ref_id="EV-2", text="空腹血糖 7.2 mmol/L（偏高）", record_ref="rec-a"),
        ),
    )
    provider, captured = capturing_provider()
    service = QAService(provider)
    asyncio.run(service.answer("顺序测试", shuffled))
    pairs = captured[0].context.evidence_pairs()
    # 传入顺序被保留，编号/正文/来源三者不错位（旧实现按编号排序会打乱）
    assert pairs == [
        ("EV-9", "尿酸 480 μmol/L（偏高）", "rec-b"),
        ("EV-2", "空腹血糖 7.2 mmol/L（偏高）", "rec-a"),
    ]


def test_mismatched_citation_is_removed() -> None:
    """编号存在但正文属于另一条证据 → 判定引用错记录并移除。"""
    service = QAService(
        fake_provider("血糖 7.2 mmol/L 偏高 [EV:EV-2]，请复查。")
    )
    answer = asyncio.run(service.answer("血糖如何？", build_qa_context()))
    # EV-2 对应尿酸，句子讲的却是血糖（EV-1 的正文）→ 引用错配
    assert answer.invalid_citations_removed == ("EV-2",)
    assert "[EV:EV-2]" not in answer.content
    assert "不匹配" in answer.content


def test_correct_pairing_is_accepted_with_records() -> None:
    service = QAService(
        fake_provider("空腹血糖 7.2 mmol/L 偏高 [EV:EV-1]，尿酸 480 μmol/L 偏高 [EV:EV-2]。")
    )
    answer = asyncio.run(service.answer("情况如何？", build_qa_context()))
    assert answer.citations == ("EV-1", "EV-2")
    assert answer.invalid_citations_removed == ()
    assert answer.citation_records == (("EV-1", "rec-1"), ("EV-2", "rec-2"))


def test_multiple_and_duplicate_citations_deduplicated() -> None:
    service = QAService(
        fake_provider(
            "空腹血糖 7.2 mmol/L 偏高 [EV:EV-1]；再次强调 [EV:EV-1] 需复查。"
            "尿酸 480 μmol/L 偏高 [EV:EV-2]。"
        )
    )
    answer = asyncio.run(service.answer("重复引用", build_qa_context()))
    assert answer.citations == ("EV-1", "EV-2"), "重复引用只记一次"
    assert answer.citation_records == (("EV-1", "rec-1"), ("EV-2", "rec-2"))


def test_duplicate_text_evidence_keeps_distinct_refs() -> None:
    """两条证据正文完全相同：编号与来源仍各自绑定，不互相顶替。"""
    two_same = QAContext(
        patient_ref="P-002",
        findings=(
            EvidenceItem(ref_id="EV-A", text="尿蛋白 阳性（+）", record_ref="rec-x"),
            EvidenceItem(ref_id="EV-B", text="尿蛋白 阳性（+）", record_ref="rec-y"),
        ),
    )
    provider, captured = capturing_provider()
    service = QAService(provider)
    asyncio.run(service.answer("重复正文", two_same))
    pairs = captured[0].context.evidence_pairs()
    assert pairs == [
        ("EV-A", "尿蛋白 阳性（+）", "rec-x"),
        ("EV-B", "尿蛋白 阳性（+）", "rec-y"),
    ]


def test_plan_only_context_has_no_fabricated_evidence() -> None:
    """无证据条目时不得臆造配对，提示词给明确空标记。"""
    provider, captured = capturing_provider()
    service = QAService(provider)
    asyncio.run(
        service.answer("空上下文", QAContext(patient_ref="P-003", plan_summary="方案 v1"))
    )
    context = captured[0].context
    assert context.evidence_pairs() == []
    assert context.format_evidence_block() == "（无证据条目）"


def test_plan_summary_not_mixed_into_evidence_pairs() -> None:
    """方案摘要进入 findings 文本，但不得混入证据配对（否则会被误引用）。"""
    provider, captured = capturing_provider()
    service = QAService(provider)
    asyncio.run(service.answer("方案问题", build_qa_context()))
    context = captured[0].context
    refs = [ref for ref, _, _ in context.evidence_pairs()]
    assert refs == ["EV-1", "EV-2"]
    assert all("snapshot-7" not in text for _, text, _ in context.evidence_pairs())


# ---- 共享引用校验链路（与 T10 统一口径） ----


def test_shared_validator_accepts_known_refs() -> None:
    bindings = [
        CitationBinding(ref_id="EV-1", text="空腹血糖 7.2 mmol/L", record_ref="rec-1"),
        CitationBinding(ref_id="EV-2", text="尿酸 480 μmol/L", record_ref="rec-2"),
    ]
    verdict = validate_citations(["EV-1", "EV-2"], bindings)
    assert verdict.accepted == ["EV-1", "EV-2"]
    assert verdict.unknown == [] and verdict.mismatched == []
    assert verdict.is_clean is True
    assert verdict.rejected == []


def test_shared_validator_flags_unknown_refs() -> None:
    bindings = [CitationBinding(ref_id="EV-1", text="空腹血糖 7.2 mmol/L")]
    verdict = validate_citations(["EV-9", "EV-1"], bindings)
    assert verdict.unknown == ["EV-9"]
    assert verdict.accepted == ["EV-1"]


def test_shared_validator_flags_mismatch_by_content() -> None:
    """编号存在但句子讲的是另一条证据 → 计入 mismatched 并从 accepted 移除。"""
    bindings = [
        CitationBinding(ref_id="EV-1", text="空腹血糖 7.2 mmol/L"),
        CitationBinding(ref_id="EV-2", text="尿酸 480 μmol/L"),
    ]
    content = "血糖 7.2 mmol/L 偏高 [EV:EV-2]。"
    verdict = validate_citations(["EV-2"], bindings, content=content)
    assert verdict.mismatched == ["EV-2"]
    assert verdict.accepted == []
    assert verdict.rejected == ["EV-2"]


def test_shared_validator_tolerates_json_only_citations() -> None:
    """T10 的 JSON 形态没有行内编号：content 留空时只做存在性校验。"""
    bindings = [CitationBinding(ref_id="EV-1", text="空腹血糖 7.2 mmol/L")]
    verdict = validate_citations(["EV-1", "EV-404"], bindings, content="")
    assert verdict.accepted == ["EV-1"]
    assert verdict.unknown == ["EV-404"]
    assert verdict.mismatched == []


def test_h08_and_t10_use_same_validator() -> None:
    """两条链路对同一份证据集合给出同一判定（审查要求统一校验链路）。"""
    model_output = "血糖 7.2 mmol/L 偏高 [EV:EV-2]，另见 [EV:EV-404]。"
    bindings = [
        CitationBinding(ref_id="EV-1", text="空腹血糖 7.2 mmol/L", record_ref="rec-1"),
        CitationBinding(ref_id="EV-2", text="尿酸 480 μmol/L", record_ref="rec-2"),
    ]

    # H08：行内编号 + 正文
    h08 = validate_citations(
        extract_inline_citations(model_output), bindings, content=model_output
    )

    # T10：JSON 里 resolved 出的编号（存在性校验），再单独做错配检查
    t10_refs = ["EV-2", "EV-404"]
    t10 = validate_citations(t10_refs, bindings, content=model_output)

    assert h08.unknown == t10.unknown == ["EV-404"]
    assert h08.mismatched == t10.mismatched == ["EV-2"]
    assert h08.rejected == t10.rejected


def test_citation_catalog_projection_matches_t10_shape() -> None:
    """H08 上下文可投影成 T10 的 citation 列表形态，编号与内容不错位。"""
    context = make_context(
        evidence_items=[
            StructuredEvidenceItem(ref_id="EV-9", text="空腹血糖 7.2 mmol/L", record_ref="rec-a"),
            StructuredEvidenceItem(ref_id="EV-2", text="尿酸 480 μmol/L", record_ref="rec-b"),
        ]
    )
    catalog = context.citation_catalog()
    assert [c["ref"] for c in catalog] == ["EV-9", "EV-2"]
    assert catalog[0]["label"] == "空腹血糖 7.2 mmol/L"
    assert catalog[0]["record_ref"] == "rec-a"


def test_qa_service_routes_through_shared_module() -> None:
    """引用守卫不得另起私有实现：判定应来自 app.llm.citations。"""
    import inspect

    from app.llm import qa as qa_module

    source = inspect.getsource(qa_module)
    assert "validate_citations" in source
    assert "_fingerprint_hit" not in source, "错配判定应只在共享模块里实现"
