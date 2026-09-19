"""E-GraphSAGE: edge-featured, inductive GraphSAGE for flow (edge) classification.

Based on Lo et al., "E-GraphSAGE: A Graph Neural Network based Intrusion
Detection System for IoT" (NOMS 2022), with two documented changes:

1. Messages combine the neighbour's embedding with the connecting flow's
   features, m_{u->v} = W_m [h_u || e_uv], instead of aggregating raw edge
   features only. In the original formulation the second layer re-aggregates
   the same raw edge features, so information never travels beyond one hop;
   including h_u makes layer k see k-hop context.
2. Incoming and outgoing flows are aggregated separately. Direction is the
   whole point for NIDS: a scanner has huge OUT-degree, a DDoS victim huge
   IN-degree. A single undirected mean would blur the two.

    h_v^{k} = ReLU( W_k [ h_v^{k-1} || mean_{u→v} m_in(h_u, e_uv) || mean_{v→w} m_out(h_w, e_vw) ] )

Edge classifier:  logits(u→v) = MLP( [ h_u^K || h_v^K || P e_uv ] )
(`edge_skip=True` adds the projected edge's own features, so the GNN can never
be worse than a per-flow model merely because features were diluted by
aggregation — which keeps the FFNN-vs-GNN ablation about *structure*.)

Inductiveness: all weights are shared functions of features/neighbourhoods;
there are no per-node embeddings or ID lookups, so the model applies to hosts
never seen in training (brief §1, §7).
"""
from __future__ import annotations

import torch
from torch import nn
from torch_geometric.nn import MessagePassing


class EdgeSAGEConv(MessagePassing):
    def __init__(self, node_in: int, edge_in: int, out: int):
        super().__init__(aggr="mean", flow="source_to_target")
        self.msg = nn.Linear(node_in + edge_in, out)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        return self.propagate(edge_index, x=x, edge_attr=edge_attr)

    def message(self, x_j: torch.Tensor, edge_attr: torch.Tensor) -> torch.Tensor:
        return torch.relu(self.msg(torch.cat([x_j, edge_attr], dim=-1)))


class EGraphSAGELayer(nn.Module):
    def __init__(self, node_in: int, edge_in: int, out: int):
        super().__init__()
        self.agg_in = EdgeSAGEConv(node_in, edge_in, out)   # flows arriving at v
        self.agg_out = EdgeSAGEConv(node_in, edge_in, out)  # flows leaving v (edges reversed)
        self.update = nn.Linear(node_in + 2 * out, out)

    def forward(self, x, edge_index, edge_attr):
        h_in = self.agg_in(x, edge_index, edge_attr)
        h_out = self.agg_out(x, edge_index.flip(0), edge_attr)
        return self.update(torch.cat([x, h_in, h_out], dim=-1))


class EGraphSAGE(nn.Module):
    def __init__(self, node_in: int, edge_in: int, num_classes: int, hidden: int = 64,
                 layers: int = 2, dropout: float = 0.2, edge_skip: bool = True):
        super().__init__()
        self.edge_skip = edge_skip
        self.layers = nn.ModuleList()
        d = node_in
        for _ in range(layers):
            self.layers.append(EGraphSAGELayer(d, edge_in, hidden))
            d = hidden
        self.dropout = nn.Dropout(dropout)
        cls_in = 2 * hidden + (hidden if edge_skip else 0)
        if edge_skip:
            self.edge_proj = nn.Linear(edge_in, hidden)
        self.classifier = nn.Sequential(
            nn.Linear(cls_in, hidden), nn.ReLU(), nn.Dropout(dropout), nn.Linear(hidden, num_classes)
        )

    def node_embeddings(self, x, edge_index, edge_attr):
        h = x
        for layer in self.layers:
            h = self.dropout(torch.relu(layer(h, edge_index, edge_attr)))
        return h

    def edge_features(self, x, edge_index, edge_attr, target_edges: torch.Tensor | None = None):
        h = self.node_embeddings(x, edge_index, edge_attr)
        ei = edge_index if target_edges is None else edge_index[:, target_edges]
        ea = edge_attr if target_edges is None else edge_attr[target_edges]
        parts = [h[ei[0]], h[ei[1]]]
        if self.edge_skip:
            parts.append(torch.relu(self.edge_proj(ea)))
        return torch.cat(parts, dim=-1)

    def forward(self, x, edge_index, edge_attr, target_edges: torch.Tensor | None = None):
        """Return logits for `target_edges` (indices into edge_index), or all edges."""
        return self.classifier(self.edge_features(x, edge_index, edge_attr, target_edges))

    def forward_with_embedding(self, x, edge_index, edge_attr):
        """(logits, embedding): embedding = the classifier's hidden layer, one vector per
        flow. Used for prototype-distance novelty scores and embedding-drift detection."""
        z = self.classifier[1](self.classifier[0](self.edge_features(x, edge_index, edge_attr)))
        return self.classifier[3](z), z
