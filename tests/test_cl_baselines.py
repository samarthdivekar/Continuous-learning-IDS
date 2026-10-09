"""Standard continual-learning baselines on the graph model (review point 3): LwF and DER++."""
import numpy as np


def _data(cfg, tmp_path):
    from src.preprocessing.pipeline import load_processed, prepare_dataset
    from tests.conftest import synthetic_raw_csv
    raw = tmp_path / "raw.csv"
    synthetic_raw_csv(raw)
    prepare_dataset(cfg, csv_files=[raw])
    return load_processed(cfg)


def test_lwf_and_derpp_run_through_the_task_sequence(cfg, tmp_path):
    from src.evaluation.continual import run_task_sequence
    data = _data(cfg, tmp_path)
    res = run_task_sequence(cfg, data, ["gnn_lwf", "gnn_derpp"], tmp_path / "res")
    assert res is not None


def test_derpp_stores_outputs_and_lwf_has_a_teacher(cfg, tmp_path):
    import torch
    from src.training.learners import make_learner
    data = _data(cfg, tmp_path)
    nf, node_in = data.meta["n_features"], data.graphs(0, "train")[0].x.shape[1]
    der = make_learner("gnn_derpp", cfg, nf, 8, torch.device("cpu"), node_in=node_in)
    g0 = data.graphs(0, "train")
    der.learn(g0, tag="t0")
    assert set(der.der_logits) == {int(g.window_id) for g in g0}
    k = next(iter(der.der_logits))
    assert der.der_logits[k].shape[1] == 8
    lwf = make_learner("gnn_lwf", cfg, nf, 8, torch.device("cpu"), node_in=node_in)
    lwf.learn(g0, tag="t0")
    before = {n: p.clone() for n, p in lwf.model.state_dict().items()}
    lwf.learn(data.graphs(1, "train"), tag="t1")                  # the second task trains against a teacher
    changed = any(not torch.equal(before[n], p) for n, p in lwf.model.state_dict().items())
    assert changed and np.isfinite(lwf.history[-1]["final_loss"])
