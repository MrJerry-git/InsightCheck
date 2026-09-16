"""机器学习模型接口与已实现的推荐模型 Adapter。"""

from app.ml.interfaces import RecommendationModel, RiskModel
from app.ml.recommendation.model import DeepFMRecommendationModel

__all__ = ["DeepFMRecommendationModel", "RecommendationModel", "RiskModel"]
