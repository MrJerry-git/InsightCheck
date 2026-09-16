from collections.abc import Sequence

import torch
from torch import nn


class DeepFMNetwork(nn.Module):
    """标准 FM 二阶交互与多层感知机共享 embedding 的 DeepFM 网络。"""

    def __init__(
        self,
        *,
        feature_count: int,
        field_count: int,
        embedding_dim: int,
        hidden_dims: Sequence[int],
        dropout: float,
    ) -> None:
        super().__init__()
        self.linear_embedding = nn.Embedding(feature_count, 1)
        self.feature_embedding = nn.Embedding(feature_count, embedding_dim)
        layers: list[nn.Module] = []
        input_dim = field_count * embedding_dim
        for hidden_dim in hidden_dims:
            layers.extend([nn.Linear(input_dim, hidden_dim), nn.ReLU(), nn.Dropout(dropout)])
            input_dim = hidden_dim
        layers.append(nn.Linear(input_dim, 1))
        self.deep = nn.Sequential(*layers)
        nn.init.normal_(self.linear_embedding.weight, mean=0.0, std=0.01)
        nn.init.normal_(self.feature_embedding.weight, mean=0.0, std=0.01)

    def forward(self, feature_ids: torch.Tensor, feature_values: torch.Tensor) -> torch.Tensor:
        values = feature_values.unsqueeze(-1)
        linear_logit = (self.linear_embedding(feature_ids) * values).sum(dim=1)
        embeddings = self.feature_embedding(feature_ids) * values
        summed = embeddings.sum(dim=1)
        fm_logit = 0.5 * (summed.square() - embeddings.square().sum(dim=1)).sum(
            dim=1, keepdim=True
        )
        deep_logit = self.deep(embeddings.flatten(start_dim=1))
        return torch.sigmoid(linear_logit + fm_logit + deep_logit).squeeze(-1)
