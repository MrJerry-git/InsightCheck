from abc import ABC, abstractmethod

from app.llm.contracts import (
    HealthSummaryRequest,
    LLMResponse,
    PatientChatRequest,
    RecommendationExplanationRequest,
)


class LLMProvider(ABC):
    """自然语言解释的稳定接口；不拥有项目推荐权。"""

    @abstractmethod
    async def generate_health_summary(self, request: HealthSummaryRequest) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def explain_recommendation(
        self,
        request: RecommendationExplanationRequest,
    ) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    async def chat_with_patient_context(self, request: PatientChatRequest) -> LLMResponse:
        raise NotImplementedError
