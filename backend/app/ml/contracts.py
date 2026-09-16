from dataclasses import dataclass, field
from typing import TypeAlias

FeatureValue: TypeAlias = str | int | float | bool | None
FeatureRecord: TypeAlias = dict[str, FeatureValue]


@dataclass(frozen=True, slots=True)
class TrainingDataset:
    records: tuple[FeatureRecord, ...]
    labels: tuple[FeatureValue, ...]
    dataset_version: str


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    metrics: dict[str, float]
    dataset_version: str
    model_version: str


@dataclass(frozen=True, slots=True)
class ModelArtifactMetadata:
    model_version: str
    feature_pipeline_version: str
    created_at_iso: str
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RiskPrediction:
    subject_id: str
    risk_code: str
    probability: float
    risk_model_version: str
    feature_pipeline_version: str
    trace_id: str
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RankedExamItem:
    exam_item_id: str
    deepfm_score: float
    model_version: str
    feature_version: str
    trace_id: str

    @property
    def score(self) -> float:
        return self.deepfm_score

    @property
    def recommendation_model_version(self) -> str:
        return self.model_version

    @property
    def feature_pipeline_version(self) -> str:
        return self.feature_version
