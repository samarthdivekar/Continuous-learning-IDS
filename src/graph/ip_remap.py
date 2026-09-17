"""IP-remapping evaluation modes (brief §7: IP leakage).

In CIC-IDS datasets the attacker is usually one fixed IP, so a graph model
could "cheat" by learning WHO talks rather than HOW they talk. Three
mitigations are implemented; this module provides the test for the third.

Mode `permute` — bijective random relabelling of all hosts at test time.
    Tests identity leakage: if the model had memorised specific hosts (e.g.
    through learned node embeddings), predictions would change. Our model has
    no node identity inputs (constant/degree features only), so this is
    EXACTLY invariant by construction; the experiment verifies that
    empirically and the number is reported anyway.

Mode `random_src` — every flow's source is replaced by a random host drawn
    from a large pool (default 65,536 addresses), independently per flow.
    Tests topology reliance: the attacker is no longer a single hub, so fan-out
    / fan-in patterns created by one source IP disappear. A drop here is
    expected and informative — it quantifies how much of the GNN's advantage
    comes from host-level structure versus per-flow behaviour. This mirrors
    the source-IP randomisation used by Lo et al. (E-GraphSAGE, 2022).

Both operate on test graphs only; training data is never altered.
"""
from __future__ import annotations

import numpy as np
import torch
from torch_geometric.data import Data

from src.graph.window_builder import node_features


def _copy_meta(src: Data, dst: Data) -> Data:
    for k in ("window_id", "task_id", "split", "window_start", "window_end", "flow_idx"):
        if k in src:
            dst[k] = src[k]
    return dst


def permute_ips_in_graph(g: Data, seed: int) -> Data:
    """Random bijection on node ids (equivalent to permuting IP addresses)."""
    gen = torch.Generator().manual_seed(seed)
    perm = torch.randperm(g.num_nodes, generator=gen)        # old id -> new id
    inv = torch.empty_like(perm)
    inv[perm] = torch.arange(g.num_nodes)                    # new id -> old id
    out = Data(x=g.x[inv], edge_index=perm[g.edge_index], edge_attr=g.edge_attr, y=g.y, num_nodes=g.num_nodes)
    return _copy_meta(g, out)


def reassign_sources(g: Data, pool_size: int, seed: int, node_feature_kind: str | None = None) -> Data:
    """Replace each flow's source host by an independent random host from a pool."""
    rng = np.random.default_rng(seed)
    n_e = g.edge_index.shape[1]
    dst_old = g.edge_index[1].numpy()
    new_src = rng.integers(0, pool_size, size=n_e)
    # destinations keep their identity (namespace 0), new sources live in namespace 1
    keys = np.concatenate([np.stack([np.zeros(n_e, np.int64), dst_old], 1),
                           np.stack([np.ones(n_e, np.int64), new_src], 1)])
    _, codes = np.unique(keys, axis=0, return_inverse=True)
    codes = codes.reshape(-1)
    edge_index = torch.from_numpy(np.stack([codes[n_e:], codes[:n_e]]).astype(np.int64))
    num_nodes = int(codes.max()) + 1
    kind = node_feature_kind or ("constant" if g.x.shape[1] == 1 else "degree")
    out = Data(x=node_features(num_nodes, edge_index, kind), edge_index=edge_index,
               edge_attr=g.edge_attr, y=g.y, num_nodes=num_nodes)
    return _copy_meta(g, out)


def make_transform(mode: str, seed: int, pool_size: int = 65536):
    if mode == "none":
        return None
    if mode == "permute":
        return lambda g: permute_ips_in_graph(g, seed + int(g.window_id))
    if mode == "random_src":
        return lambda g: reassign_sources(g, pool_size, seed + int(g.window_id))
    raise ValueError(f"Unknown IP remap mode {mode!r}")
