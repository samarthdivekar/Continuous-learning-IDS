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
