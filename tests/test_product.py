import numpy as np
import torch

from src.explain.explain import explain_edge, summarize
from src.product.incidents import build_incidents, calibrate_threshold, incident_metrics
from src.product.response import propose_action
from src.training.learners import make_learner
from tests.test_graph import _toy

NAMES = ["Benign", "BruteForce", "DoS", "WebAttack", "Infiltration", "Botnet", "PortScan", "DDoS"]


def _probs(pred, conf, K=8):
    p = np.full((len(pred), K), (1 - conf) / (K - 1))
    p[np.arange(len(pred)), pred] = conf
    return p


def test_scan_and_ddos_become_one_incident_each_and_noise_stays_separate():
    # scanner 10.0.0.9 -> 30 hosts; DDoS: 40 sources -> 10.0.0.1; plus two stray false alarms
    src = ["10.0.0.9"] * 30 + [f"172.16.0.{i}" for i in range(40)] + ["192.168.1.5", "192.168.1.7"]
    dst = [f"10.1.0.{i}" for i in range(30)] + ["10.0.0.1"] * 40 + ["8.8.8.8", "1.1.1.1"]
    pred = np.array([6] * 30 + [7] * 40 + [6, 6])
    y = np.array([6] * 30 + [7] * 40 + [0, 0])
    inc = build_incidents(np.array(src), np.array(dst), _probs(pred, 0.9), NAMES, threshold=0.5, y_cat=y)
    sizes = sorted(i["n_flows"] for i in inc)
    assert sizes == [1, 1, 30, 40]
    ddos = next(i for i in inc if i["category"] == "DDoS")
    assert ddos["key_host"] == "10.0.0.1" and ddos["key_role"] == "destination"
    m = incident_metrics(inc, y)
    assert m["incidents"] == 4 and m["true_incidents"] == 2 and m["attack_flows_in_true_incidents"] == 1.0


def test_budget_threshold_limits_benign_alerts():
    rng = np.random.default_rng(0)
    y = np.zeros(10_000, int)
    probs = np.c_[1 - rng.random(10_000) * 0.6, rng.random((10_000, 7)) * 0.01]
    probs /= probs.sum(1, keepdims=True)
    t = calibrate_threshold(probs, y, budget=0.01)
    assert abs(((1 - probs[:, 0]) >= t).mean() - 0.01) < 0.002


def test_actions_are_dry_run_and_match_pattern():
    scan = {"category": "PortScan", "key_host": "10.0.0.9", "key_role": "source", "n_sources": 1,
            "n_destinations": 30, "key_host_flows": 30}
    ddos = {"category": "DDoS", "key_host": "10.0.0.1", "key_role": "destination", "n_sources": 40,
            "n_destinations": 1, "key_host_flows": 40}
    a, b = propose_action(scan), propose_action(ddos)
    assert a["action"] == "block_source" and "10.0.0.9" in a["rules"]["linux"] and a["dry_run"]
    assert b["action"] == "rate_limit_to_victim" and "10.0.0.1" in b["rules"]["linux"]
    assert propose_action({**scan, "key_host": "not-an-ip"})["action"] == "investigate"


def test_explanation_structure_and_summary(cfg):
    torch.manual_seed(0)
    g = _toy()
    L = make_learner("gnn_ewc_replay", cfg, n_features=2, num_classes=8, device=torch.device("cpu"))
    L.learn([g], tag="t")
    exp = explain_edge(L, g, 0, ["flow_duration", "syn_flag_count"])
    assert exp["structure"]["source_flows"] == 3 and exp["structure"]["source_distinct_peers"] == 3
    assert len(exp["features"]) == 2 and 0 <= exp["confidence"] <= 1
    assert 0 <= exp["context_share"] <= 1
    assert "confidence" in summarize(exp, NAMES)
