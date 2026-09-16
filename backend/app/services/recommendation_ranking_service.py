from app.ml.interfaces import RecommendationModel
from app.ml.recommendation.candidate_generator import CandidateGenerator
from app.ml.recommendation.schemas import (
    DeepFMRankedExamItem,
    RecommendationRankingRequest,
    RecommendationRankingResponse,
)

MEDICAL_DISCLAIMER = (
    "本系统基于历史体检数据提供健康趋势分析与体检项目辅助推荐，不构成疾病诊断、"
    "医疗处方或治疗建议，最终体检方案应由具有资质的医务人员结合实际情况确认。"
)


class RecommendationRankingService:
    """编排高召回候选生成与 DeepFM 排名；不执行最终安全筛选。"""

    def __init__(
        self,
        model: RecommendationModel,
        candidate_generator: CandidateGenerator | None = None,
    ) -> None:
        self.model = model
        self.candidate_generator = candidate_generator or CandidateGenerator()

    def rank(self, request: RecommendationRankingRequest) -> RecommendationRankingResponse:
        candidate_set = self.candidate_generator.generate(request.candidate_exam_items)
        ranked = self.model.rank(
            request.model_copy(update={"candidate_exam_items": candidate_set.items})
        )
        return RecommendationRankingResponse(
            items=[
                DeepFMRankedExamItem(
                    exam_item_id=item.exam_item_id,
                    deepfm_score=item.deepfm_score,
                    model_version=item.model_version,
                    feature_version=item.feature_version,
                    trace_id=item.trace_id,
                )
                for item in ranked
            ],
            candidate_generator_version=candidate_set.generator_version,
            safety_rules_applied=candidate_set.safety_rules_applied,
            requires_rule_engine=candidate_set.requires_rule_engine,
            disclaimer=MEDICAL_DISCLAIMER,
        )
