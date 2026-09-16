from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Self

from app.ml.contracts import (
    EvaluationResult,
    FeatureRecord,
    ModelArtifactMetadata,
    RankedExamItem,
    RiskPrediction,
    TrainingDataset,
)

if TYPE_CHECKING:
    from app.ml.recommendation.schemas import (
        RecommendationRankingRequest,
        RecommendationTrainingDataset,
    )


class RiskModel(ABC):
    """健康风险预测模型的稳定接口；未来由 LightGBM Adapter 实现。"""

    @abstractmethod
    def train(self, dataset: TrainingDataset) -> ModelArtifactMetadata:
        raise NotImplementedError

    @abstractmethod
    def predict(self, subject_id: str, features: FeatureRecord) -> Sequence[RiskPrediction]:
        raise NotImplementedError

    @abstractmethod
    def evaluate(self, dataset: TrainingDataset) -> EvaluationResult:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def load(cls, artifact_path: Path) -> Self:
        raise NotImplementedError

    @abstractmethod
    def save(self, artifact_path: Path, metadata: ModelArtifactMetadata) -> None:
        raise NotImplementedError


class RecommendationModel(ABC):
    """Patient × ExamItem 匹配模型的稳定接口；未来由 DeepFM Adapter 实现。"""

    @abstractmethod
    def train(self, dataset: "RecommendationTrainingDataset") -> ModelArtifactMetadata:
        raise NotImplementedError

    @abstractmethod
    def rank(
        self,
        request: "RecommendationRankingRequest",
    ) -> Sequence[RankedExamItem]:
        raise NotImplementedError

    @abstractmethod
    def evaluate(self, dataset: "RecommendationTrainingDataset") -> EvaluationResult:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def load(cls, artifact_path: Path) -> Self:
        raise NotImplementedError

    @abstractmethod
    def save(self, artifact_path: Path, metadata: ModelArtifactMetadata) -> None:
        raise NotImplementedError
