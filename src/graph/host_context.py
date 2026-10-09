"""Per-window host aggregates for per-flow models: the "is it the graph, or just context?" baseline.

A graph model sees who talks to whom. The cheapest way to give a per-flow model the same kind of information
is to attach, to every flow, simple counts computed over the same 5,000-flow window: how many flows its source
sent, to how many hosts and ports; how many its destination received, from how many hosts; how many flows the
pair exchanged. If a per-flow model with these columns matches the GNN, "the graph helps" really means
"window context helps" (review point 3).

Everything comes from the window graph itself (edge_index and the dst_port column), so the per-flow models
use exactly the windows, flows and splits the GNN uses, and nothing outside the window.
"""
from __future__ import annotations

import numpy as np
import torch

CONTEXT_NAMES = [
    "src_flows_out", "src_distinct_dst", "src_distinct_dst_ports", "src_flows_in",
    "dst_flows_in", "dst_distinct_src", "dst_distinct_ports_hit", "dst_flows_out",
    "pair_flows",
]
N_CONTEXT = len(CONTEXT_NAMES)


def _count(keys: np.ndarray) -> np.ndarray:
    """For every row, how often its key occurs."""
    _, inv, cnt = np.unique(keys, return_inverse=True, return_counts=True)
    return cnt[inv]


def _distinct(group: np.ndarray, value: np.ndarray) -> np.ndarray:
    """For every row, how many distinct `value`s its `group` has."""
    pairs = np.unique(np.stack([group, value], axis=1), axis=0)
    g_ids, n = np.unique(pairs[:, 0], return_counts=True)
    lookup = dict(zip(g_ids.tolist(), n.tolist()))
    return np.fromiter((lookup[g] for g in group.tolist()), dtype=np.int64, count=len(group))


def host_context(edge_index: torch.Tensor, port_col: np.ndarray | None) -> np.ndarray:
    """(n_edges, N_CONTEXT) float32: log1p counts, scaled by log1p(window flows) into roughly [0, 1]."""
    src, dst = edge_index.cpu().numpy()
    n = len(src)
    if n == 0:
        return np.zeros((0, N_CONTEXT), dtype=np.float32)
    ports = np.zeros(n, dtype=np.int64) if port_col is None else np.unique(port_col, return_inverse=True)[1]
    pair = src.astype(np.int64) * (int(max(src.max(), dst.max())) + 1) + dst
    out_by_host = np.bincount(src, minlength=int(max(src.max(), dst.max())) + 1)
    in_by_host = np.bincount(dst, minlength=len(out_by_host))
    cols = [
        out_by_host[src], _distinct(src, dst), _distinct(src, ports), in_by_host[src],
        in_by_host[dst], _distinct(dst, src), _distinct(dst, ports), out_by_host[dst],
        _count(pair),
    ]
    feats = np.log1p(np.stack(cols, axis=1).astype(np.float64)) / np.log1p(max(n, 2))
    return feats.astype(np.float32)


# Feature order is fixed by src/ingestion/columns.py: dst_port is column 0 of every processed dataset
# (tests/test_host_context.py checks it against the processed metadata).
PORT_INDEX = 0


def flow_inputs(g) -> torch.Tensor:
    """A window's flow features with the host context appended (computed per call: a few ms per window)."""
    port = g.edge_attr[:, PORT_INDEX].numpy()
    ctx = torch.from_numpy(host_context(g.edge_index, port))
    return torch.cat([g.edge_attr, ctx], dim=1)
