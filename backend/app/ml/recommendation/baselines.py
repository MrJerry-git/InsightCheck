from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.ml.contracts import EvaluationResult, ModelArtifactMetadata
from app.ml.recommendation.metrics import ranking_metrics_at_k
from app.ml.recommendation.schemas import (
    RecommendationRankingRequest,
    RecommendationTrainingDataset,
)
from app.rules.models import RuleEvaluationResult


@dataclass(frozen=True, slots=True)
class BaselineRankedItem:
    exam_item_id: str
    match_score: float
    baseline_version: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class RuleBaselineEvaluationCase:
    request: RecommendationRankingRequest
    outcomes_by_exam_item: Mapping[str, RuleEvaluationResult]
    relevant_item_ids: frozenset[str]


def _age_bucket(age: int | None) -> str:
    if age is None:
        return "unknown"
    return f"{(age // 10) * 10}s"


class AgeGenderBaseline:
    """按年龄段、性别和项目的平滑历史阳性率形成可执行 baseline。"""

    def __init__(self, model_version: str = "age-gender-baseline-v1", smoothing: float = 2.0):
        self.model_version = model_version
        self.smoothing = smoothing
        self.feature_pipeline_version: str | None = None
        self._group_counts: dict[tuple[str, str, str], tuple[float, int]] = {}
        self._item_counts: dict[str, tuple[float, int]] = {}
        self._global_rate = 0.0

    def train(self, dataset: RecommendationTrainingDataset) -> ModelArtifactMetadata:
        group_totals: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        item_totals: dict[str, list[float]] = defaultdict(list)
        labels: list[float] = []
        for example in dataset.examples:
            key = (
                _age_bucket(example.patient.age),
                example.patient.gender,
                example.exam_item.exam_code,
            )
            group_totals[key].append(example.label)
            item_totals[example.exam_item.exam_code].append(example.label)
            labels.append(example.label)
        self._group_counts = {
            key: (sum(values), len(values)) for key, values in group_totals.items()
        }
        self._item_counts = {
            key: (sum(values), len(values)) for key, values in item_totals.items()
        }
        self._global_rate = sum(labels) / len(labels)
        self.feature_pipeline_version = dataset.feature_pipeline_version
        return ModelArtifactMetadata(
            model_version=self.model_version,
            feature_pipeline_version=dataset.feature_pipeline_version,
            created_at_iso=datetime.now(UTC).isoformat(),
            extra={
                "dataset_version": dataset.dataset_version,
                "variant": "age_gender_baseline",
                "is_demo": str(dataset.is_demo).lower(),
            },
        )

    def rank(self, request: RecommendationRankingRequest) -> list[BaselineRankedItem]:
        if self.feature_pipeline_version is None:
            raise RuntimeError("age/gender baseline has not been trained")
        scores: list[BaselineRankedItem] = []
        for item in request.candidate_exam_items:
            item_positive, item_count = self._item_counts.get(item.exam_code, (0.0, 0))
            item_rate = (
                item_positive / item_count if item_count else self._global_rate
            )
            key = (_age_bucket(request.patient.age), request.patient.gender, item.exam_code)
            positive, count = self._group_counts.get(key, (0.0, 0))
            score = (positive + self.smoothing * item_rate) / (count + self.smoothing)
            scores.append(
                BaselineRankedItem(
                    exam_item_id=item.exam_item_id,
                    match_score=score,
                    baseline_version=self.model_version,
                    trace_id=request.trace_id,
                )
            )
        return sorted(scores, key=lambda item: (-item.match_score, item.exam_item_id))

    def evaluate(self, dataset: RecommendationTrainingDataset) -> EvaluationResult:
        totals = {
            f"{metric}@{k}": 0.0
            for k in (5, 10)
            for metric in ("Precision", "Recall", "NDCG")
        }
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for example in dataset.examples:
            key = (example.patient.patient_id, example.patient.feature_as_of_date.isoformat())
            groups[key].append(example)
        for index, examples in enumerate(groups.values()):
            ranking = self.rank(
                RecommendationRankingRequest(
                    patient=examples[0].patient,
                    candidate_exam_items=[example.exam_item for example in examples],
                    trace_id=f"baseline-evaluation-{index}",
                )
            )
            relevant = {
                example.exam_item.exam_item_id for example in examples if example.label >= 0.5
            }
            ranked_ids = [item.exam_item_id for item in ranking]
            for k in (5, 10):
                values = ranking_metrics_at_k(ranked_ids, relevant, k)
                totals[f"Precision@{k}"] += values.precision
                totals[f"Recall@{k}"] += values.recall
                totals[f"NDCG@{k}"] += values.ndcg
        return EvaluationResult(
            metrics={key: value / len(groups) for key, value in totals.items()},
            dataset_version=dataset.dataset_version,
            model_version=self.model_version,
        )


class RuleOnlyBaseline:
    """只消费外部 Rule Engine 决定，不在推荐模型层定义医疗规则。"""

    version = "rule-only-external-decisions-v1"

    def rank(
        self,
        request: RecommendationRankingRequest,
        outcomes_by_exam_item: Mapping[str, RuleEvaluationResult],
    ) -> list[BaselineRankedItem]:
        ranked: list[BaselineRankedItem] = []
        for item in request.candidate_exam_items:
            outcome = outcomes_by_exam_item.get(item.exam_item_id)
            score = outcome.adjusted_score if outcome is not None else 0.5
            ranked.append(
                BaselineRankedItem(
                    exam_item_id=item.exam_item_id,
                    match_score=score,
                    baseline_version=self.version,
                    trace_id=request.trace_id,
                )
            )
        return sorted(ranked, key=lambda item: (-item.match_score, item.exam_item_id))

    def evaluate(
        self,
        cases: Sequence[RuleBaselineEvaluationCase],
        *,
        dataset_version: str,
    ) -> EvaluationResult:
        if not cases:
            raise ValueError("at least one rule baseline evaluation case is required")
        totals = {
            f"{metric}@{k}": 0.0
            for k in (5, 10)
            for metric in ("Precision", "Recall", "NDCG")
        }
        for case in cases:
            ranking = self.rank(case.request, case.outcomes_by_exam_item)
            ranked_ids = [item.exam_item_id for item in ranking]
            for k in (5, 10):
                values = ranking_metrics_at_k(ranked_ids, case.relevant_item_ids, k)
                totals[f"Precision@{k}"] += values.precision
                totals[f"Recall@{k}"] += values.recall
                totals[f"NDCG@{k}"] += values.ndcg
        return EvaluationResult(
            metrics={key: value / len(cases) for key, value in totals.items()},
            dataset_version=dataset_version,
            model_version=self.version,
        )
