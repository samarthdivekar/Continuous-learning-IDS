"""Edge-centric neighbour sampling (GraphSAGE-style) for large windows.

For a set of target edges we take their endpoints as the hop-0 frontier and,
for each hop, keep at most `fanout` incident edges (in either direction) per
frontier node, chosen uniformly at random. The union of sampled edges and the
target edges forms a subgraph; the loss is computed on target edges only.

Node features (including degree features) are taken from the FULL window, so
a hub still looks like a hub after sampling.

Pure torch/numpy on purpose: PyG's LinkNeighborLoader needs the compiled
pyg-lib / torch-sparse extensions, whose Windows wheels lag behind torch
releases. Windows are bounded (count-mode windows are 5k flows), so this path
is only exercised for very large time-mode windows.
"""
from __future__ import annotations

import numpy as np
import torch
from torch_geometric.data import Data


class IncidenceIndex:
    """CSR-style index: node -> incident edge ids (both directions)."""

    def __init__(self, edge_index: torch.Tensor, num_nodes: int):
        ei = edge_index.cpu().numpy()
        n_e = ei.shape[1]
        nodes = np.concatenate([ei[0], ei[1]])
        edges = np.concatenate([np.arange(n_e), np.arange(n_e)])
        order = np.argsort(nodes, kind="stable")
        self.nodes_sorted = nodes[order]
        self.edges_sorted = edges[order]
        self.ptr = np.searchsorted(self.nodes_sorted, np.arange(num_nodes + 1))

    def sample(self, frontier: np.ndarray, fanout: int, rng: np.random.Generator) -> np.ndarray:
        starts, ends = self.ptr[frontier], self.ptr[frontier + 1]
        deg = ends - starts
        total = int(deg.sum())
        if total == 0:
            return np.empty(0, dtype=np.int64)
        group = np.repeat(np.arange(len(frontier)), deg)
        offsets = np.arange(total) - np.repeat(np.cumsum(deg) - deg, deg)
        cand = self.edges_sorted[np.repeat(starts, deg) + offsets]
        keys = rng.random(total)
        order = np.lexsort((keys, group))       # random order inside each node's group
        rank = np.arange(total) - np.repeat(np.cumsum(deg) - deg, deg)
        keep = order[rank < fanout]
        return cand[keep]


def sample_subgraph(g: Data, target_edges: np.ndarray, fanouts: list[int],
                    rng: np.random.Generator, index: IncidenceIndex | None = None) -> Data:
    index = index or IncidenceIndex(g.edge_index, g.num_nodes)
    ei = g.edge_index.cpu().numpy()
    selected = [np.asarray(target_edges, dtype=np.int64)]
    frontier = np.unique(np.concatenate([ei[0, target_edges], ei[1, target_edges]]))
    visited = set(frontier.tolist())
    for fan in fanouts:
        new_edges = index.sample(frontier, fan, rng)
        selected.append(new_edges)
        nxt = np.unique(np.concatenate([ei[0, new_edges], ei[1, new_edges]]))
        frontier = np.array([n for n in nxt if n not in visited], dtype=np.int64)
        visited.update(frontier.tolist())
        if len(frontier) == 0:
            break
    edges = np.unique(np.concatenate(selected))
    nodes, inv = np.unique(ei[:, edges], return_inverse=True)
    inv = inv.reshape(2, -1)
    target_mask = np.isin(edges, target_edges)
    sub = Data(
        x=g.x[torch.from_numpy(nodes)],
        edge_index=torch.from_numpy(inv.astype(np.int64)),
        edge_attr=g.edge_attr[torch.from_numpy(edges)],
        y=g.y[torch.from_numpy(edges)],
        num_nodes=len(nodes),
    )
    sub.target_mask = torch.from_numpy(target_mask)
    # which flows carry a label (active learning labels only a few per window)
    sub.label_mask = g.label_mask[torch.from_numpy(edges)] if "label_mask" in g else torch.ones(len(edges), dtype=torch.bool)
    return sub


def iter_training_subgraphs(g: Data, cfg_ns: dict, rng: np.random.Generator, shuffle: bool = True):
    """Yield (sub)graphs for training on window `g`.

    Small windows are yielded whole (target_mask = all edges). Large windows
    are split into random edge mini-batches with sampled neighbourhoods.
    """
    n_e = g.edge_index.shape[1]
    enabled = cfg_ns.get("enabled", "auto")
    use = enabled is True or (enabled == "auto" and n_e > int(cfg_ns["max_edges_full"]))
    if not use:
        out = Data(x=g.x, edge_index=g.edge_index, edge_attr=g.edge_attr, y=g.y, num_nodes=g.num_nodes)
        out.target_mask = torch.ones(n_e, dtype=torch.bool)
        out.label_mask = g.label_mask if "label_mask" in g else torch.ones(n_e, dtype=torch.bool)
        yield out
        return
    index = IncidenceIndex(g.edge_index, g.num_nodes)
    perm = rng.permutation(n_e) if shuffle else np.arange(n_e)
    bs = int(cfg_ns["batch_edges"])
    for s in range(0, n_e, bs):
        yield sample_subgraph(g, perm[s:s + bs], list(cfg_ns["fanouts"]), rng, index)
