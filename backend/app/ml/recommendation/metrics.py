import math
from collections.abc import Sequence, Set
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RankingMetricsAtK:
    precision: float
    recall: float
    ndcg: float


def ranking_metrics_at_k(
    ranked_item_ids: Sequence[str], relevant_item_ids: Set[str], k: int
) -> RankingMetricsAtK:
    if k <= 0:
        raise ValueError("k must be positive")
    top_items = list(ranked_item_ids[:k])
    if not top_items:
        return RankingMetricsAtK(precision=0.0, recall=0.0, ndcg=0.0)

    hits = [1.0 if item_id in relevant_item_ids else 0.0 for item_id in top_items]
    precision = sum(hits) / len(top_items)
    recall = sum(hits) / len(relevant_item_ids) if relevant_item_ids else 0.0
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal_hits = min(len(relevant_item_ids), len(top_items))
    ideal_dcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    ndcg = dcg / ideal_dcg if ideal_dcg else 0.0
    return RankingMetricsAtK(precision=precision, recall=recall, ndcg=ndcg)
