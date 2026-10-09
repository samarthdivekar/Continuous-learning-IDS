"""Per-flow host-context features computed inside the flow's own window (review question RQ1).

Does the graph help, or would plain host statistics do? This module gives a tabular model the same host-level
information a graph exposes, as columns: for every flow, counted inside its own window from the endpoints
(IP addresses, here the window's node ids) and destination ports only — never from labels:

  src_out_degree        flows sent by the flow's source host
  src_distinct_dsts     distinct destination hosts that source talked to
  src_distinct_ports    distinct destination ports that source used
  dst_in_degree         flows received by the flow's destination host
  dst_distinct_srcs     distinct source hosts that talked to that destination
  pair_flows            flows between this source and this destination

and each of the six divided by the window's flow count (12 columns). Pure functions, no side effects; nothing
here is used by the existing models.
"""
from __future__ import annotations

import numpy as np

CONTEXT_COLUMNS = ["src_out_degree", "src_distinct_dsts", "src_distinct_ports",
                   "dst_in_degree", "dst_distinct_srcs", "pair_flows"]
CONTEXT_NAMES = CONTEXT_COLUMNS + [f"{c}_per_flow" for c in CONTEXT_COLUMNS]


def _distinct_per(key: np.ndarray, other: np.ndarray, n_keys: int) -> np.ndarray:
    """For each key id, how many distinct `other` values occur with it."""
    pairs = np.unique(np.stack([key, other], 1), axis=0)
    return np.bincount(pairs[:, 0], minlength=n_keys)


def window_context(src: np.ndarray, dst: np.ndarray, port: np.ndarray) -> np.ndarray:
    """(n_flows, 12) float32 context features for one window.

    `src`, `dst`: host ids of each flow's endpoints (any integers; equal id = same host).
    `port`: each flow's destination port (any value whose equality means "same port", e.g. the scaled column).
    """
    n = len(src)
    if n == 0:
        return np.zeros((0, len(CONTEXT_NAMES)), dtype=np.float32)
    hosts, inv = np.unique(np.concatenate([src, dst]), return_inverse=True)
    s, d = inv[:n], inv[n:]
    h = len(hosts)
    _, p = np.unique(port, return_inverse=True)
    out_deg = np.bincount(s, minlength=h)
    in_deg = np.bincount(d, minlength=h)
    s_dsts = _distinct_per(s, d, h)
    s_ports = _distinct_per(s, p.astype(np.int64), h)
    d_srcs = _distinct_per(d, s, h)
    _, pair_inv, pair_cnt = np.unique(s * h + d, return_inverse=True, return_counts=True)
    raw = np.stack([out_deg[s], s_dsts[s], s_ports[s], in_deg[d], d_srcs[d], pair_cnt[pair_inv]], 1).astype(np.float64)
    return np.concatenate([raw, raw / n], 1).astype(np.float32)


def graph_context(g, port_col: int = 0) -> np.ndarray:
    """Context features for every edge (flow) of a window graph; column `port_col` of edge_attr is dst_port."""
    ei = g.edge_index.numpy()
    return window_context(ei[0], ei[1], g.edge_attr[:, port_col].numpy())
