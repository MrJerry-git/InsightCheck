"""确定性模板 LLM 实现（H08）。

只使用受控结构化上下文生成解释文本；无网络、无模型依赖，回答中
显式引用证据条目。模板模式在响应的 llm_model 中标注 local-template，
不冒充真实模型输出。
"""

from __future__ import annotations

import uuid

from app.llm.contracts import (
    HealthSummaryRequest,
    LLMResponse,
    PatientChatRequest,
    RecommendationExplanationRequest,
)
from app.llm.provider import LLMProvider

TEMPLATE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "insightcheck/llm-template")


class TemplatedLLMProvider(LLMProvider):
    """local-template 实现：确定性、可测试、显式标注模式。"""

    async def generate_health_summary(self, request: HealthSummaryRequest) -> LLMResponse:
        context = request.context
        lines = [
            f"【模板解释，非模型输出】受检者 {context.patient_id} 的健康摘要：",
            f"- 结构化发现 {len(context.normalized_findings)} 条，趋势摘要 "
            f"{len(context.trend_summaries)} 条，风险摘要 {len(context.risk_summaries)} 条。",
        ]
        lines.extend(f"- 发现：{item}" for item in context.normalized_findings)
        lines.extend(f"- 趋势：{item}" for item in context.trend_summaries)
        lines.append(
            "以上内容基于已保存的结构化记录整理，不构成诊断；请结合医师意见确认。"
        )
        trace = uuid.uuid5(
            TEMPLATE_NAMESPACE,
            f"summary:{context.patient_id}:{len(context.evidence_refs)}",
        )
        return LLMResponse(
            content="\n".join(lines),
            llm_model="local-template",
            trace_id=str(trace),
        )

    async def explain_recommendation(
        self, request: RecommendationExplanationRequest
    ) -> LLMResponse:
        context = request.context
        lines = [
            f"【模板解释，非模型输出】推荐 {request.recommendation_id} 的依据：",
            f"- 推荐摘要 {len(context.recommendation_summaries)} 条，证据条目 "
            f"{len(context.evidence_refs)} 条。",
        ]
        lines.extend(f"- {item}" for item in context.recommendation_summaries)
        lines.append("推荐结果由规则与模型链路产生，最终方案以人工审核版本为准。")
        trace = uuid.uuid5(
            TEMPLATE_NAMESPACE,
            f"explain:{context.patient_id}:{request.recommendation_id}",
        )
        return LLMResponse(
            content="\n".join(lines),
            llm_model="local-template",
            trace_id=str(trace),
        )

    async def chat_with_patient_context(self, request: PatientChatRequest) -> LLMResponse:
        context = request.context
        lines = [
            "【模板问答，非模型输出】基于当前档案的结构化记录回答：",
            f"- 已登记发现 {len(context.normalized_findings)} 条、趋势摘要 "
            f"{len(context.trend_summaries)} 条。",
            "- 可追溯证据条目（编号与正文成对）：",
        ]
        pairs = context.evidence_pairs()
        if pairs:
            lines.extend(
                f"  · [EV:{ref_id}] {text}（来源记录：{record_ref or '未标注'}）"
                for ref_id, text, record_ref in pairs
            )
        else:
            lines.append("  · （无）")
        lines.extend(
            [
                "- 具体问题需医师结合原始报告确认；本回答不修改任何已保存方案。",
                f"收到的问题：{request.user_message}",
            ]
        )
        trace = uuid.uuid5(
            TEMPLATE_NAMESPACE,
            f"chat:{context.patient_id}:{request.user_message}",
        )
        return LLMResponse(
            content="\n".join(lines),
            llm_model="local-template",
            trace_id=str(trace),
        )
