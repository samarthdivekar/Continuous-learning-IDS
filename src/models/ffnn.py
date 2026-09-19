"""Plain feed-forward network on per-flow features (ablation / fallback).

Same edge features the GNN sees, no graph structure. Trained with the same
EWC and replay machinery, so FFNN-vs-GNN isolates the contribution of
topology.
"""
from __future__ import annotations

from torch import nn


class FFNN(nn.Module):
    def __init__(self, in_dim: int, num_classes: int, hidden=(256, 128), dropout: float = 0.2):
        super().__init__()
        layers, d = [], in_dim
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU(), nn.Dropout(dropout)]
            d = h
        layers.append(nn.Linear(d, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)

    def forward_with_embedding(self, x):
        """(logits, embedding): embedding = the last hidden layer (after ReLU)."""
        z = self.net[:-1](x)
        return self.net[-1](z), z
