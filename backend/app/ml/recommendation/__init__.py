"""DeepFM 个性化体检项目匹配模块。"""

from app.ml.recommendation.candidate_generator import CandidateGenerator
from app.ml.recommendation.model import DeepFMRecommendationModel

__all__ = ["CandidateGenerator", "DeepFMRecommendationModel"]
