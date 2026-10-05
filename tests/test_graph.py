import numpy as np
import torch

from src.graph.ip_remap import permute_ips_in_graph, reassign_sources
from src.graph.sampling import IncidenceIndex, iter_training_subgraphs, sample_subgraph
from src.graph.window_builder import build_window_graph, edge_labels
from src.models.egraphsage import EGraphSAGE


def _toy():
    src = np.array(["1.1.1.1", "1.1.1.1", "1.1.1.1", "2.2.2.2", "3.3.3.3"])
    dst = np.array(["9.9.9.9", "8.8.8.8", "7.7.7.7", "9.9.9.9", "1.1.1.1"])
    feats = np.arange(10, dtype=np.float32).reshape(5, 2)
    y = np.array([6, 6, 6, 0, 0])
    return build_window_graph(src, dst, feats, y, "degree", window_id=7, task_id=1, split=0)


def test_window_graph_structure():
    g = _toy()
    assert g.num_nodes == 6
    assert g.edge_index.shape == (2, 5)
    # same IP -> same node inside a window
    assert g.edge_index[0, 0] == g.edge_index[0, 1] == g.edge_index[0, 2] == g.edge_index[1, 4]
    # edge features are exactly the flow features, in order; no IP data anywhere in tensors
    assert torch.equal(g.edge_attr, torch.arange(10, dtype=torch.float32).reshape(5, 2))
    # degree features: 1.1.1.1 has out-degree 3, in-degree 1
    n = int(g.edge_index[0, 0])
    assert torch.allclose(g.x[n], torch.tensor([1.0, np.log1p(3), np.log1p(1)], dtype=torch.float32))
    assert edge_labels(g, "binary").tolist() == [1, 1, 1, 0, 0]
    assert g.window_id == 7


def test_constant_node_features():
    g = build_window_graph(np.array(["a"]), np.array(["b"]), np.zeros((1, 2), np.float32), np.array([0]), "constant")
    assert torch.equal(g.x, torch.ones(2, 1))


def test_ip_permutation_is_isomorphic_and_model_invariant():
    g = _toy()
    torch.manual_seed(0)
    model = EGraphSAGE(3, 2, 8, hidden=8).eval()
    p = permute_ips_in_graph(g, seed=1)
    assert not torch.equal(p.edge_index, g.edge_index) or g.num_nodes < 2
    with torch.no_grad():
        a = model(g.x, g.edge_index, g.edge_attr)
        b = model(p.x, p.edge_index, p.edge_attr)
    assert torch.allclose(a, b, atol=1e-5)


def test_reassign_sources_breaks_fanout():
    g = _toy()
    r = reassign_sources(g, pool_size=10_000, seed=0)
    assert r.edge_index.shape == g.edge_index.shape
    assert torch.equal(r.edge_attr, g.edge_attr) and torch.equal(r.y, g.y)
    # with a huge pool, the 3 flows from the scanner almost surely get distinct sources
    assert len(set(r.edge_index[0, :3].tolist())) == 3


def test_neighbor_sampling_respects_fanout_and_targets():
    rng = np.random.default_rng(0)
    n_e = 400
    src = np.array(["hub"] * n_e)
    dst = np.array([f"h{i}" for i in range(n_e)])
    g = build_window_graph(src, dst, rng.normal(size=(n_e, 3)).astype(np.float32), np.zeros(n_e, int), "degree")
    idx = IncidenceIndex(g.edge_index, g.num_nodes)
    hub = int(g.edge_index[0, 0])
    sampled = idx.sample(np.array([hub]), 25, rng)
    assert len(sampled) == 25 and len(set(sampled.tolist())) == 25
    sub = sample_subgraph(g, np.array([0, 1]), [5, 5], rng, idx)
    assert int(sub.target_mask.sum()) == 2
    assert sub.edge_index.max() < sub.num_nodes
    # hub keeps its full-graph degree feature after sampling
    assert torch.isclose(sub.x[:, 1].max(), torch.tensor(np.log1p(n_e), dtype=torch.float32))
    # auto mode: small graph -> whole graph
    cfg_ns = {"enabled": "auto", "max_edges_full": 1000, "fanouts": [5], "batch_edges": 100}
    assert len(list(iter_training_subgraphs(g, cfg_ns, rng))) == 1
    cfg_ns["max_edges_full"] = 100
    subs = list(iter_training_subgraphs(g, cfg_ns, rng))
    assert len(subs) == 4 and sum(int(s.target_mask.sum()) for s in subs) == n_e


def test_label_mask_flows_through_sampling_and_remap():
    rng = np.random.default_rng(0)
    g = _toy()
    g.label_mask = torch.tensor([True, False, False, True, False])
    whole = next(iter_training_subgraphs(g, {"enabled": False, "max_edges_full": 10, "fanouts": [5], "batch_edges": 2}, rng))
    assert torch.equal(whole.label_mask, g.label_mask)
    subs = list(iter_training_subgraphs(g, {"enabled": True, "max_edges_full": 1, "fanouts": [5], "batch_edges": 2}, rng))
    assert sum(int((s.label_mask & s.target_mask).sum()) for s in subs) == 2
    r = reassign_sources(g, pool_size=100, seed=0)
    assert torch.equal(r.label_mask, g.label_mask)


def test_topology_augmented_learner_trains_and_masks_labels(cfg):
    from src.training.learners import make_learner
    torch.manual_seed(0)
    gs = []
    for w in range(3):
        g = _toy(); g.window_id = w
        g.label_mask = torch.tensor([True, True, False, False, True])
        gs.append(g)
    cfg = dict(cfg, graph={**cfg["graph"], "topology_augment": {"prob": 1.0, "pool_size": 50}})
    L = make_learner("gnn_ewc_replay_topo", cfg, n_features=2, num_classes=8, device=torch.device("cpu"))
    stats = L.learn(gs, tag="t")
    assert stats.steps > 0 and np.isfinite(stats.final_loss)
    logits, z = L.predict_details(gs[0])
    assert logits.shape == (5, 8) and z.shape[0] == 5


def test_temporal_split_trains_on_past_and_tests_on_future():
    """Per task: every train window precedes every val window, which precedes every test window,
    with gap windows dropped so no test window is adjacent to a training window."""
    import numpy as np
    import pandas as pd
    from src.graph.window_builder import SPLIT_CODES, temporal_split

    win_task = pd.Series([0] * 20 + [1] * 10, index=range(30))        # window_id -> task
    ordinal = win_task.groupby(win_task).cumcount()
    split = temporal_split(ordinal, win_task, {"train": 0.7, "val": 0.1, "gap": 1})
    for task in (0, 1):
        s = split[win_task == task]
        o = ordinal[win_task == task]
        tr, va, te = (o[s == SPLIT_CODES[k]] for k in ("train", "val", "test"))
        assert len(tr) and len(va) and len(te)
        assert tr.max() < va.min() and va.max() < te.min()          # strictly chronological
        assert va.min() - tr.max() >= 2 and te.min() - va.max() >= 2  # a gap window between blocks
        assert (s == -1).sum() == 2                                   # exactly two gap windows per task
    # task 0 (20 windows): 12 train, gap, 2 val, gap, 4 test — test is the last 20%
    s0 = split[win_task == 0].to_numpy()
    assert list(np.bincount(s0[s0 >= 0], minlength=3)) == [12, 2, 4]
    # a short task (10 windows) still keeps a test and a validation block
    s1 = split[win_task == 1].to_numpy()
    assert list(np.bincount(s1[s1 >= 0], minlength=3)) == [5, 1, 2]


def test_temporal_split_drops_gap_windows_and_keeps_interleaved_cache_key(cfg):
    import pandas as pd
    from src.graph.window_builder import assign_windows_and_splits, cache_key
    from src.utils.config import apply_overrides

    ts = pd.date_range("2017-07-03", periods=300, freq="s")
    df = pd.DataFrame({"ts": ts, "segment_id": 0, "task_id": 0})
    win = {"mode": "count", "flows_per_window": 10}
    out = assign_windows_and_splits(df, win, {"strategy": "temporal", "temporal": {"train": 0.7, "val": 0.1, "gap": 1}})
    per_window = out.groupby("window_id")["split"].first()
    assert set(per_window.unique()) <= {0, 1, 2}                      # no gap code reaches the pipeline
    assert out["window_id"].nunique() == 30 - 2                       # two gap windows removed
    # interleaved keeps its historical hash; temporal gets a different one
    inter = apply_overrides(cfg, ["split.strategy=interleaved"])
    assert cache_key(inter) == cache_key({**cfg, "split": {k: v for k, v in cfg["split"].items()
                                                         if k not in ("strategy", "temporal")}})
    assert cache_key(apply_overrides(cfg, ["split.strategy=temporal"])) != cache_key(inter)


def test_attack_aware_temporal_split_keeps_test_traffic_for_an_early_attack():
    """An attack that happens only early in its task has no test traffic under a plain temporal
    split; the attack-aware split still trains on its earliest windows and tests on its latest."""
    import pandas as pd
    from src.graph.window_builder import SPLIT_CODES, attack_aware_temporal_split, temporal_split

    # 40 windows in one task; the attack ("Web") appears only in windows 0-14
    rows = [{"window_id": w, "task_id": 0, "category": "Web" if w < 15 else "Benign"} for w in range(40)]
    df = pd.DataFrame(rows)
    win_task = df.groupby("window_id", sort=True)["task_id"].first()
    ordinal = win_task.groupby(win_task).cumcount()
    tcfg = {"train": 0.7, "val": 0.1, "gap": 1}

    plain = temporal_split(ordinal, win_task, tcfg)
    attack_windows = win_task.index[win_task.index < 15]
    assert (plain.loc[attack_windows] == SPLIT_CODES["test"]).sum() == 0     # the failure being fixed

    aware = attack_aware_temporal_split(df, ordinal, win_task, {0: "Web"}, tcfg)
    att = aware.loc[attack_windows]
    assert (att == SPLIT_CODES["test"]).sum() >= 1 and (att == SPLIT_CODES["train"]).sum() >= 1
    # still chronological inside the attack's span: every training window precedes every test window
    assert att[att == SPLIT_CODES["train"]].index.max() < att[att == SPLIT_CODES["test"]].index.min()
