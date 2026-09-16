import pytest

from app.ml.recommendation.metrics import ranking_metrics_at_k


def test_ranking_metrics_match_hand_calculated_example() -> None:
    ranked = ["A", "B", "C", "D"]
    relevant = {"A", "C"}

    at_two = ranking_metrics_at_k(ranked, relevant, 2)
    at_three = ranking_metrics_at_k(ranked, relevant, 3)

    assert at_two.precision == 0.5
    assert at_two.recall == 0.5
    assert at_two.ndcg == pytest.approx(0.6131471928)
    assert at_three.precision == pytest.approx(2 / 3)
    assert at_three.recall == 1.0
    assert at_three.ndcg == pytest.approx(0.9197207891)
