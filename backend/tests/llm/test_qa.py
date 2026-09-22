"""H08 问答服务：模板模式、OpenAI 兼容适配器与引用守卫。

异步接口用 asyncio.run() 驱动，不引入新的测试依赖。
"""

import asyncio

import pytest

from app.llm.contracts import (
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
