import inspect

from app.llm.provider import LLMProvider
from app.ml.interfaces import RecommendationModel, RiskModel


def test_required_model_interfaces_are_abstract() -> None:
    assert inspect.isabstract(RiskModel)
    assert RiskModel.__abstractmethods__ == {"train", "predict", "evaluate", "load", "save"}
    assert inspect.isabstract(RecommendationModel)
    assert RecommendationModel.__abstractmethods__ == {
        "train",
        "rank",
        "evaluate",
        "load",
        "save",
    }


def test_llm_provider_interface_is_abstract() -> None:
    assert inspect.isabstract(LLMProvider)
    assert LLMProvider.__abstractmethods__ == {
        "generate_health_summary",
        "explain_recommendation",
        "chat_with_patient_context",
    }
