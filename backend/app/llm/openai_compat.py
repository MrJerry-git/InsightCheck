"""OpenAI 兼容聊天接口适配器（H08）。

真实模型问答的最小实现：调用 OpenAI 兼容 /chat/completions 接口。
- base_url / api_key / model 全部来自注入配置，密钥不进 Git 与前端；
- 超时、HTTP 错误、限流显式抛出 LLMProviderError，不降级为编造内容；
- 未配置凭据时 is_available()=False，由调用方决定回退模板模式并在
  响应中标注。
网络调用使用标准库（urllib），不新增运行依赖；阻塞调用经
asyncio.to_thread 包装。
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.llm.contracts import (
    HealthSummaryRequest,
    LLMResponse,
    PatientChatRequest,
    RecommendationExplanationRequest,
)
from app.llm.provider import LLMProvider

SYSTEM_PROMPT = (
    "你是体检报告解释助手。只依据给定的结构化上下文回答，"
    "引用证据时使用 [EV:<编号>] 格式，编号必须来自上下文的证据列表；"
    "不得编造引用、不得输出疾病概率、不得修改任何已保存方案；"
    "回答使用中文，并说明内容不构成诊断。"
)


@dataclass(frozen=True)
class OpenAICompatConfig:
    base_url: str          # 如 https://api.example.com/v1
    api_key: str           # 环境变量注入；不落盘、不进 Git
    model: str
    timeout_seconds: float = 30.0
    temperature: float = 0.0


class LLMProviderError(RuntimeError):
    """模型调用失败：超时/网络/HTTP 错误统一转为显式异常。"""


class OpenAICompatibleLLMProvider(LLMProvider):
    """OpenAI 兼容供应商适配器。"""

    def __init__(self, config: OpenAICompatConfig) -> None:
        self.config = config

    def is_available(self) -> bool:
        return bool(
            self.config.base_url.strip()
            and self.config.api_key.strip()
            and self.config.model.strip()
        )

    async def generate_health_summary(self, request: HealthSummaryRequest) -> LLMResponse:
        context = request.context
        user_prompt = (
            "请基于以下结构化上下文生成健康摘要。\n"
            f"发现：{context.normalized_findings}\n"
            f"趋势：{context.trend_summaries}\n"
            f"风险：{context.risk_summaries}\n"
            f"证据编号：{context.evidence_refs}"
        )
        return await self._chat(
            user_prompt,
            f"summary:{context.patient_id}:{tuple(context.evidence_refs)}",
        )

    async def explain_recommendation(
        self, request: RecommendationExplanationRequest
    ) -> LLMResponse:
        context = request.context
        user_prompt = (
            f"请解释推荐 {request.recommendation_id} 的依据。\n"
            f"推荐摘要：{context.recommendation_summaries}\n"
            f"证据编号：{context.evidence_refs}"
        )
        return await self._chat(
            user_prompt,
            f"explain:{context.patient_id}:{request.recommendation_id}",
        )

    async def chat_with_patient_context(self, request: PatientChatRequest) -> LLMResponse:
        context = request.context
        user_prompt = (
            "受检者提问，请基于结构化上下文回答。\n"
            f"发现：{context.normalized_findings}\n"
            f"趋势：{context.trend_summaries}\n"
            f"证据编号：{context.evidence_refs}\n"
            f"问题：{request.user_message}"
        )
        return await self._chat(
            user_prompt,
            f"chat:{context.patient_id}:{request.user_message}",
        )

    # ---- HTTP ----

    async def _chat(self, user_prompt: str, trace_seed: str) -> LLMResponse:
        if not self.is_available():
            raise LLMProviderError(
                "模型问答未配置（base_url/api_key/model 缺失）；"
                "请配置凭据或回退到 local-template 模式"
            )
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        content = await asyncio.to_thread(self._post_chat, payload)
        import uuid

        trace_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.config.model}:{trace_seed}"))
        return LLMResponse(content=content, llm_model=self.config.model, trace_id=trace_id)

    def _post_chat(self, payload: dict) -> str:
        base = self.config.base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        if urlsplit(url).scheme != "https":
            raise LLMProviderError("模型接口必须使用 HTTPS")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise LLMProviderError(f"模型接口 HTTP 错误：{exc.code}") from exc
        except urllib.error.URLError as exc:
            raise LLMProviderError(f"模型接口连接失败：{exc.reason}") from exc
        except TimeoutError as exc:
            raise LLMProviderError("模型接口请求超时") from exc

        choices = data.get("choices") or []
        if not choices or "message" not in choices[0]:
            raise LLMProviderError("模型接口返回格式异常：缺少 choices[0].message")
        content = choices[0]["message"].get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError("模型接口返回内容为空")
        return content
