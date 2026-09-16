"""结构化病灶术语、匹配评分与纵向趋势能力。"""

from app.features.lesion.matcher import LesionMatcher
from app.features.lesion.scorer import LesionScorer
from app.features.lesion.terminology import LesionTerminology
from app.features.lesion.trend import LesionTrendAnalyzer

__all__ = ["LesionMatcher", "LesionScorer", "LesionTerminology", "LesionTrendAnalyzer"]
