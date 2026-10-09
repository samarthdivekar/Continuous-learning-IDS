"""Per-window host statistics for every flow: the "does the graph help, or would host statistics do?" baseline.

For each flow, computed inside its own window from the endpoints (hosts, from the IPs) and the destination
port only, never from labels:

    src_out_degree        flows the flow's source sends in the window
    src_distinct_dst      distinct destination hosts that source talks to
    src_distinct_dports   distinct destination ports that source hits
    dst_in_degree         flows the flow's destination receives in the window
    dst_distinct_src      distinct source hosts that destination hears from
    pair_flows            flows between this (source, destination) pair

and each of the six divided by the window's flow count (suffix `_frac`). Raw counts, no scaling: the
tree model this feeds is invariant to monotone transforms.

This is deliberately separate from src/graph/host_context.py (log-scaled counts used by the ffnn_ctx_* /
xgboost_ctx_* models of the continual runs); it is used only by experiments/run_context_baseline.py.
"""
from __future__ import annotations

import numpy as np

COUNT_NAMES = ["src_out_degree", "src_distinct_dst", "src_distinct_dports",
               "dst_in_degree", "dst_distinct_src", "pair_flows"]
CONTEXT_FEATURES = COUNT_NAMES + [f"{n}_frac" for n in COUNT_NAMES]
N_CONTEXT_FEATURES = len(CONTEXT_FEATURES)


def _count(keys: np.ndarray) -> np.ndarray:
    """For every row, how many rows share its key."""
    _, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    return cnt[inv.reshape(-1)]


def _distinct(group: np.ndarray, value: np.ndarray) -> np.ndarray:
    """For every row, how many distinct `value`s occur with its `group`."""
    pairs = np.unique(np.stack([group, value], axis=1), axis=0)
    g_ids, n = np.unique(pairs[:, 0], return_counts=True)
    return n[np.searchsorted(g_ids, group)]


def window_context(src: np.ndarray, dst: np.ndarray, dst_port: np.ndarray) -> np.ndarray:
    """(n_flows, 12) float64 for ONE window. `src` / `dst` are host ids (any integers identifying the IPs within
    the window), `dst_port` any per-flow value that is equal exactly when the destination port is equal."""
    src = np.asarray(src, dtype=np.int64)
    dst = np.asarray(dst, dtype=np.int64)
    n = len(src)
    if n == 0:
        return np.zeros((0, N_CONTEXT_FEATURES), dtype=np.float64)
    port_id = np.unique(np.asarray(dst_port), return_inverse=True)[1].reshape(-1).astype(np.int64)
    counts = np.stack([
        _count(src),
        _distinct(src, dst),
        _distinct(src, port_id),
        _count(dst),
        _distinct(dst, src),
        _count(np.stack([src, dst], axis=1)),
    ], axis=1).astype(np.float64)
    return np.concatenate([counts, counts / n], axis=1)
