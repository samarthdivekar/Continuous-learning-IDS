from collections import Counter

import numpy as np
import torch
from torch_geometric.data import Data

from src.models.replay_buffer import GraphReplayBuffer, TabularReplayBuffer


def _g(cat_counts: dict, wid: int) -> Data:
    y = torch.cat([torch.full((n,), c) for c, n in cat_counts.items()])
    n = len(y)
    return Data(x=torch.ones(n + 1, 1), edge_index=torch.stack([torch.zeros(n, dtype=torch.long),
                                                                torch.arange(1, n + 1)]),
                edge_attr=torch.zeros(n, 2), y=y, window_id=wid)


def test_graph_pools_by_category_and_capacity():
    buf = GraphReplayBuffer(graphs_per_class=3, graphs_per_step=2, seed=0)
    for w in range(20):
        buf.add(_g({0: 10, 2: 5}, w))
    buf.add(_g({0: 10, 6: 1}, 99))
    buf.add(_g({0: 10}, 100))  # benign-only: stored nowhere
    s = buf.summary()
    assert s[2] == {"stored": 3, "seen": 20}
    assert s[6] == {"stored": 1, "seen": 1}
    assert 0 not in s
    assert len(buf) == 4


def test_reservoir_is_uniform_over_stream():
    counts = Counter()
    for seed in range(400):
        buf = GraphReplayBuffer(graphs_per_class=2, seed=seed)
        for w in range(10):
            buf.add(_g({1: 3}, w))
        counts.update(g.window_id for g in buf.pools[1])
    # each of 10 windows should be kept ~ 400 * 2/10 = 80 times
    assert all(40 < counts[w] < 120 for w in range(10)), counts


def test_sample_budget_is_fixed_and_category_balanced():
    buf = GraphReplayBuffer(graphs_per_class=5, graphs_per_step=4, seed=0)
    for w in range(50):
        buf.add(_g({0: 5, 2: 50}, w))       # a huge historic category
    buf.add(_g({0: 5, 3: 2}, 1000))          # a tiny one
    buf.add(_g({0: 5, 5: 2}, 2000))
    picks = Counter()
    for _ in range(600):
        s = buf.sample()
        assert len(s) == 4                   # budget never grows with #categories
        for g in s:
            picks[int(g.y.max())] += 1
    total = sum(picks.values())
    for c in (2, 3, 5):
        assert 0.2 < picks[c] / total < 0.47, picks   # ~1/3 each, not dominated by category 2


def test_empty_buffer_samples_nothing():
    assert GraphReplayBuffer().sample() == []
    X, y = TabularReplayBuffer().sample()
    assert len(y) == 0


def test_tabular_reservoir_capacity_and_balance():
    rng = np.random.default_rng(0)
    buf = TabularReplayBuffer(flows_per_class=100, flows_per_step=300, seed=0)
    X = rng.normal(size=(10_000, 4)).astype(np.float32)
    y = np.r_[np.zeros(9_000, int), np.full(900, 2), np.full(100, 7)]
    buf.add(X, y)
    buf.add(X[:500], np.full(500, 2))
    s = buf.summary()
    assert s[0]["stored"] == 100 and s[2]["stored"] == 100 and s[7]["stored"] == 100
    assert s[2]["seen"] == 1400
    Xs, ys = buf.sample()
    assert len(ys) == 300
    frac = np.bincount(ys, minlength=8)[[0, 2, 7]] / 300
    assert (frac > 0.2).all()
    # stored rows are real rows of that category
    pool_rows = {tuple(r) for r in buf.X[7]}
    assert pool_rows <= {tuple(r) for r in X[9_900:]}
