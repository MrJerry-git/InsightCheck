from app.ml.recommendation.baselines import (
    AgeGenderBaseline,
    RuleBaselineEvaluationCase,
    RuleOnlyBaseline,
)
from app.ml.recommendation.schemas import RecommendationRankingRequest
from app.rules.models import FinalRuleStatus, RuleEvaluationResult

from .test_deepfm import exam_items, patient, training_dataset


def test_age_gender_baseline_is_trainable_and_returns_real_scores() -> None:
    baseline = AgeGenderBaseline(model_version="age-gender-demo-v1")
    baseline.train(training_dataset())

    ranking = baseline.rank(
        RecommendationRankingRequest(
            patient=patient("baseline-patient", 0.9),
            candidate_exam_items=exam_items(),
            trace_id="trace-age-gender",
        )
    )

    assert len(ranking) == 3
    assert all(0.0 <= item.match_score <= 1.0 for item in ranking)
    evaluation = baseline.evaluate(training_dataset())
    assert set(evaluation.metrics) == {
        "Precision@5",
        "Recall@5",
        "NDCG@5",
        "Precision@10",
        "Recall@10",
        "NDCG@10",
    }


def test_rule_only_baseline_consumes_external_decisions_without_defining_rules() -> None:
    request = RecommendationRankingRequest(
        patient=patient("rule-baseline-patient", 0.9),
        candidate_exam_items=exam_items(),
        trace_id="trace-rule-baseline",
    )
    outcomes = {
        "exam-a": RuleEvaluationResult(
            trace_id="rule-trace-a",
            deepfm_score=0.8,
            adjusted_score=1.0,
            final_status=FinalRuleStatus.ALLOWED,
            rule_decisions=[],
            execution_trace=[],
            rule_set_version="test-rules-v1",
        ),
        "exam-c": RuleEvaluationResult(
            trace_id="rule-trace-c",
            deepfm_score=0.8,
            adjusted_score=0.0,
            final_status=FinalRuleStatus.BLOCKED,
            rule_decisions=[],
            execution_trace=[],
            rule_set_version="test-rules-v1",
        ),
    }

    ranking = RuleOnlyBaseline().rank(request, outcomes)

    assert [item.exam_item_id for item in ranking] == ["exam-a", "exam-b", "exam-c"]
    assert [item.match_score for item in ranking] == [1.0, 0.5, 0.0]
    evaluation = RuleOnlyBaseline().evaluate(
        [
            RuleBaselineEvaluationCase(
                request=request,
                outcomes_by_exam_item=outcomes,
                relevant_item_ids=frozenset({"exam-a"}),
            )
        ],
        dataset_version="demo-rule-baseline-v1",
    )
    assert evaluation.metrics["Recall@5"] == 1.0
