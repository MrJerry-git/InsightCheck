from collections.abc import Sequence

from app.ml.recommendation.schemas import CandidateSet, ExamItemFeatures


class CandidateGenerator:
    """构建高召回候选集；不执行辐射、间隔、禁忌等医疗安全规则。"""

    version = "candidate-generator-v1"

    def generate(self, exam_items: Sequence[ExamItemFeatures]) -> CandidateSet:
        unique: dict[str, ExamItemFeatures] = {}
        for item in exam_items:
            existing = unique.get(item.exam_item_id)
            if existing is not None and existing != item:
                raise ValueError(f"conflicting exam item: {item.exam_item_id}")
            unique[item.exam_item_id] = item
        return CandidateSet(
            items=sorted(unique.values(), key=lambda item: item.exam_item_id),
            generator_version=self.version,
        )
