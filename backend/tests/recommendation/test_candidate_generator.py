from app.ml.recommendation.candidate_generator import CandidateGenerator
from app.ml.recommendation.schemas import ExamItemFeatures


def test_candidate_generator_keeps_safety_sensitive_items_for_rule_engine() -> None:
    items = [
        ExamItemFeatures(
            exam_item_id="exam-radiation",
            exam_code="CT_CHEST",
            category="imaging",
            body_part="CHEST",
            radiation=True,
            cost_level="high",
            recommended_interval_months=12,
        ),
        ExamItemFeatures(
            exam_item_id="exam-lab",
            exam_code="LIVER_PANEL",
            category="laboratory",
            body_part="LIVER",
            radiation=False,
            cost_level="low",
            recommended_interval_months=6,
        ),
    ]

    result = CandidateGenerator().generate(items)

    assert [item.exam_item_id for item in result.items] == ["exam-lab", "exam-radiation"]
    assert result.safety_rules_applied is False
    assert result.requires_rule_engine is True
