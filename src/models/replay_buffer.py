"""Experience replay buffers.

GraphReplayBuffer  — subgraph replay for the GNN (brief §5.3, "v1").
TabularReplayBuffer — flow-row replay for the FFNN ablation.

Why whole subgraphs?
    A single flow means little in isolation for a GNN: its prediction depends
    on the neighbourhood it was observed in (fan-out of its source, fan-in of
    its destination, the other flows those hosts made). Replaying a lone edge
    would give the model a context it never sees at test time. So v1 stores
    complete windowed graphs and replays them intact.

Pool design
    * One pool per ATTACK CATEGORY (not per output class). In binary mode all
      attacks share output class 1, but we still want old attack *types*
      represented evenly, so pools are keyed by category id (`g.y`).
    * A window enters the pool of every category that has at least
      `min_class_edges` edges in it (a window with DoS and PortScan edges is a
      candidate for both pools). Benign traffic is present in every stored
      window, so there is no separate benign pool.
    * Each pool is a reservoir sample (Vitter's Algorithm R) over ALL windows
      of that category seen so far, capped at `graphs_per_class`. Reservoir
      sampling keeps the pool an unbiased sample even when a category spans
      several tasks or adaptation cycles, with O(1) memory per pool.

Budget cap (brief: "Cap the total replay budget per training step")
    `sample()` always returns exactly `graphs_per_step` graphs (or fewer only
    while the buffer is still smaller than that), regardless of how many
    categories are stored. Categories are drawn uniformly first, then a graph
    uniformly from that category's pool. Therefore:
      - the old:new ratio per step is constant over the whole task sequence
        (windows have a fixed flow count in `count` mode, so graphs ≈ edges);
      - old categories are balanced against each other, instead of the
        largest historical category (e.g. DoS Hulk) dominating replay.
    Without the cap, replay volume would grow with every task and shift the
    benign/attack balance for reasons unrelated to forgetting.
"""
from __future__ import annotations

import random
from collections import defaultdict

import numpy as np
import torch


class GraphReplayBuffer:
    def __init__(self, graphs_per_class: int = 10, graphs_per_step: int = 2,
                 min_class_edges: int = 1, seed: int = 0, benign_id: int = 0):
        self.graphs_per_class = int(graphs_per_class)
        self.graphs_per_step = int(graphs_per_step)
        self.min_class_edges = int(min_class_edges)
        self.benign_id = benign_id
        self.rng = random.Random(seed)
        self.pools: dict[int, list] = defaultdict(list)     # category id -> list[Data]
        self.seen: dict[int, int] = defaultdict(int)          # category id -> windows offered so far

    def __len__(self) -> int:
        return len({id(g) for pool in self.pools.values() for g in pool})

    @property
    def categories(self) -> list[int]:
        return sorted(c for c, p in self.pools.items() if p)

    def add(self, graph) -> list[int]:
        """Offer one window graph to every eligible category pool. Returns the
        categories whose pool now contains this graph."""
        counts = torch.bincount(graph.y, minlength=self.benign_id + 1)
        added = []
        for cat in torch.nonzero(counts >= self.min_class_edges).flatten().tolist():
            if cat == self.benign_id:
                continue
            self.seen[cat] += 1
            pool = self.pools[cat]
            # Reservoir sampling (Algorithm R): the i-th window of this category
            # replaces a random slot with probability capacity / i.
            if len(pool) < self.graphs_per_class:
                pool.append(graph.cpu())
                added.append(cat)
            else:
                j = self.rng.randrange(self.seen[cat])
                if j < self.graphs_per_class:
                    pool[j] = graph.cpu()
                    added.append(cat)
        return added

    def add_many(self, graphs) -> None:
        for g in graphs:
            self.add(g)

    def sample(self, n: int | None = None) -> list:
        """Class-balanced, fixed-budget sample of stored windows (see module doc)."""
        n = self.graphs_per_step if n is None else n
        cats = self.categories
        if not cats or n <= 0:
            return []
        # 1) draw n categories uniformly (with replacement) -> exact balance in expectation
        drawn = [self.rng.choice(cats) for _ in range(n)]
        # 2) inside each category draw windows WITHOUT replacement; a window is only
        #    repeated within one step when its category's pool is smaller than the
        #    number of draws for that category. Balance across categories wins over
        #    within-step diversity.
        out = []
        for cat in sorted(set(drawn)):
            k = drawn.count(cat)
            pool = self.pools[cat]
            picks = self.rng.sample(pool, min(k, len(pool)))
            picks += [self.rng.choice(pool) for _ in range(k - len(picks))]
            out.extend(picks)
        return out

    def summary(self) -> dict:
        return {int(c): {"stored": len(p), "seen": int(self.seen[c])} for c, p in self.pools.items()}


class TabularReplayBuffer:
    """Per-category reservoir of individual flow rows for the FFNN ablation.
    Same design as the graph buffer: per-category reservoirs, uniform category
    draw, fixed rows per step."""

    def __init__(self, flows_per_class: int = 5000, flows_per_step: int = 512, seed: int = 0):
        self.capacity = int(flows_per_class)
        self.flows_per_step = int(flows_per_step)
        self.rng = np.random.default_rng(seed)
        self.X: dict[int, np.ndarray] = {}
        self.y_cat: dict[int, np.ndarray] = {}
        self.seen: dict[int, int] = defaultdict(int)

    def __len__(self) -> int:
        return int(sum(len(v) for v in self.X.values()))

    @property
    def categories(self) -> list[int]:
        return sorted(self.X)

    def add(self, X: np.ndarray, y_cat: np.ndarray) -> None:
        """Vectorised reservoir update, category by category. Benign rows are
        stored too (a benign pool keeps the FPR anchored)."""
        for cat in np.unique(y_cat):
            rows = X[y_cat == cat]
            cat = int(cat)
            if cat not in self.X:
                self.X[cat] = np.empty((0, X.shape[1]), dtype=np.float32)
            pool = self.X[cat]
            seen = self.seen[cat]
            # fill free slots first
            free = max(0, self.capacity - len(pool))
            take = rows[:free]
            pool = np.concatenate([pool, take.astype(np.float32)])
            rest = rows[free:]
            seen_after_fill = seen + len(take)
            if len(rest):
                # item i (1-based over the whole stream) replaces slot j ~ U[0, i) if j < capacity
                idx = np.arange(seen_after_fill + 1, seen_after_fill + len(rest) + 1)
                j = (self.rng.random(len(rest)) * idx).astype(np.int64)
                hit = j < self.capacity
                hj, hr = j[hit], rest[hit]
                # Later hits on the same slot overwrite earlier ones, as in the
                # sequential algorithm. NumPy does not guarantee last-writer-wins
                # for repeated fancy indices, so keep the last hit per slot explicitly.
                _, first_in_reversed = np.unique(hj[::-1], return_index=True)
                last = len(hj) - 1 - first_in_reversed
                pool[hj[last]] = hr[last]
            self.seen[cat] = seen + len(rows)
            self.X[cat] = pool
            self.y_cat[cat] = np.full(len(pool), cat, dtype=np.int64)

    def sample(self, n: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        n = self.flows_per_step if n is None else n
        cats = self.categories
        if not cats or n <= 0:
            return np.empty((0, 0), dtype=np.float32), np.empty(0, dtype=np.int64)
        chosen = self.rng.choice(cats, size=n)
        xs, ys = [], []
        for cat in np.unique(chosen):
            k = int((chosen == cat).sum())
            idx = self.rng.integers(0, len(self.X[cat]), size=k)
            xs.append(self.X[cat][idx])
            ys.append(self.y_cat[cat][idx])
        return np.concatenate(xs), np.concatenate(ys)

    def summary(self) -> dict:
        return {int(c): {"stored": len(self.X[c]), "seen": int(self.seen[c])} for c in self.categories}
