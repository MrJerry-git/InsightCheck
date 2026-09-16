from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

import torch
from torch import nn

from app.ml.contracts import (
    EvaluationResult,
    ModelArtifactMetadata,
    RankedExamItem,
)
from app.ml.interfaces import RecommendationModel
from app.ml.recommendation.encoding import RecommendationFeatureEncoder
from app.ml.recommendation.metrics import ranking_metrics_at_k
from app.ml.recommendation.network import DeepFMNetwork
from app.ml.recommendation.schemas import (
    DeepFMConfig,
    RecommendationModelVariant,
    RecommendationRankingRequest,
    RecommendationTrainingDataset,
)


class DeepFMRecommendationModel(RecommendationModel):
    """训练、排名、评估与制品管理的 DeepFM Adapter。"""

    def __init__(self, config: DeepFMConfig | None = None) -> None:
        self.config = config or DeepFMConfig()
        if self.config.variant not in {
            RecommendationModelVariant.FULL,
            RecommendationModelVariant.WITHOUT_RISK,
        }:
            raise ValueError("DeepFM model requires full or without-risk variant")
        self.encoder: RecommendationFeatureEncoder | None = None
        self.network: DeepFMNetwork | None = None
        self.metadata: ModelArtifactMetadata | None = None
        self.training_loss: float | None = None

    @property
    def risk_feature_names(self) -> tuple[str, ...]:
        return self.encoder.risk_feature_names if self.encoder else ()

    def train(self, dataset: RecommendationTrainingDataset) -> ModelArtifactMetadata:
        if self.config.variant is RecommendationModelVariant.FULL and not any(
            example.patient.risk_probabilities for example in dataset.examples
        ):
            raise ValueError("full DeepFM training requires versioned risk features")

        torch.manual_seed(self.config.random_seed)
        self.encoder = RecommendationFeatureEncoder(self.config.variant)
        self.encoder.fit(dataset.examples)
        pairs = [(example.patient, example.exam_item) for example in dataset.examples]
        encoded = self.encoder.transform(pairs)
        labels = torch.tensor([example.label for example in dataset.examples], dtype=torch.float32)
        self.network = self._new_network()
        optimizer = torch.optim.Adam(
            self.network.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        loss_function = nn.BCELoss()
        generator = torch.Generator().manual_seed(self.config.random_seed)
        for _ in range(self.config.epochs):
            order = torch.randperm(len(labels), generator=generator)
            for start in range(0, len(labels), self.config.batch_size):
                indexes = order[start : start + self.config.batch_size]
                optimizer.zero_grad()
                scores = self.network(
                    encoded.feature_ids[indexes], encoded.feature_values[indexes]
                )
                loss = loss_function(scores, labels[indexes])
                loss.backward()
                optimizer.step()
        self.network.eval()
        with torch.no_grad():
            final_scores = self.network(encoded.feature_ids, encoded.feature_values)
            self.training_loss = float(loss_function(final_scores, labels).item())
        self.metadata = ModelArtifactMetadata(
            model_version=self.config.model_version,
            feature_pipeline_version=dataset.feature_pipeline_version,
            created_at_iso=datetime.now(UTC).isoformat(),
            extra={
                "dataset_version": dataset.dataset_version,
                "variant": self.config.variant.value,
                "is_demo": str(dataset.is_demo).lower(),
            },
        )
        return self.metadata

    def rank(self, request: RecommendationRankingRequest) -> list[RankedExamItem]:
        encoder, network, metadata = self._ready_parts()
        if request.patient.feature_pipeline_version != metadata.feature_pipeline_version:
            raise ValueError("patient feature version does not match model artifact")
        if not request.candidate_exam_items:
            return []
        pairs = [(request.patient, item) for item in request.candidate_exam_items]
        encoded = encoder.transform(pairs)
        network.eval()
        with torch.no_grad():
            scores = network(encoded.feature_ids, encoded.feature_values).tolist()
        ranked = [
            RankedExamItem(
                exam_item_id=item.exam_item_id,
                deepfm_score=float(score),
                model_version=metadata.model_version,
                feature_version=metadata.feature_pipeline_version,
                trace_id=request.trace_id,
            )
            for item, score in zip(request.candidate_exam_items, scores, strict=True)
        ]
        return sorted(ranked, key=lambda item: (-item.deepfm_score, item.exam_item_id))

    def evaluate(self, dataset: RecommendationTrainingDataset) -> EvaluationResult:
        _, _, metadata = self._ready_parts()
        groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
        for example in dataset.examples:
            key = (example.patient.patient_id, example.patient.feature_as_of_date.isoformat())
            groups[key].append(example)

        totals = {
            f"{metric}@{k}": 0.0
            for k in (5, 10)
            for metric in ("Precision", "Recall", "NDCG")
        }
        for index, examples in enumerate(groups.values()):
            ranking = self.rank(
                RecommendationRankingRequest(
                    patient=examples[0].patient,
                    candidate_exam_items=[example.exam_item for example in examples],
                    trace_id=f"evaluation-{index}",
                )
            )
            relevant = {
                example.exam_item.exam_item_id for example in examples if example.label >= 0.5
            }
            ranked_ids = [item.exam_item_id for item in ranking]
            for k in (5, 10):
                metrics = ranking_metrics_at_k(ranked_ids, relevant, k)
                totals[f"Precision@{k}"] += metrics.precision
                totals[f"Recall@{k}"] += metrics.recall
                totals[f"NDCG@{k}"] += metrics.ndcg
        group_count = len(groups)
        averaged = {name: value / group_count for name, value in totals.items()}
        return EvaluationResult(
            metrics=averaged,
            dataset_version=dataset.dataset_version,
            model_version=metadata.model_version,
        )

    def save(self, artifact_path: Path, metadata: ModelArtifactMetadata) -> None:
        encoder, network, current_metadata = self._ready_parts()
        if metadata != current_metadata:
            raise ValueError("metadata does not match trained model")
        artifact_path.mkdir(parents=True, exist_ok=True)
        torch.save(network.state_dict(), artifact_path / "weights.pt")
        (artifact_path / "embedding_config.json").write_text(
            json.dumps(self.config.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (artifact_path / "feature_mapping.json").write_text(
            json.dumps(encoder.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest = asdict(metadata) | {"training_loss": self.training_loss}
        (artifact_path / "metadata.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, artifact_path: Path) -> Self:
        config = DeepFMConfig.model_validate_json(
            (artifact_path / "embedding_config.json").read_text(encoding="utf-8")
        )
        model = cls(config)
        encoder_payload = json.loads(
            (artifact_path / "feature_mapping.json").read_text(encoding="utf-8")
        )
        model.encoder = RecommendationFeatureEncoder.from_dict(encoder_payload)
        model.network = model._new_network()
        state = torch.load(
            artifact_path / "weights.pt", map_location="cpu", weights_only=True
        )
        model.network.load_state_dict(state)
        model.network.eval()
        manifest = json.loads((artifact_path / "metadata.json").read_text(encoding="utf-8"))
        model.training_loss = manifest.pop("training_loss", None)
        model.metadata = ModelArtifactMetadata(**manifest)
        return model

    def _new_network(self) -> DeepFMNetwork:
        if self.encoder is None:
            raise RuntimeError("feature encoder is unavailable")
        return DeepFMNetwork(
            feature_count=self.encoder.feature_count,
            field_count=self.encoder.field_count,
            embedding_dim=self.config.embedding_dim,
            hidden_dims=self.config.hidden_dims,
            dropout=self.config.dropout,
        )

    def _ready_parts(
        self,
    ) -> tuple[RecommendationFeatureEncoder, DeepFMNetwork, ModelArtifactMetadata]:
        if self.encoder is None or self.network is None or self.metadata is None:
            raise RuntimeError("recommendation model has not been trained or loaded")
        return self.encoder, self.network, self.metadata
