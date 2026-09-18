import json

import pandas as pd
import yaml

from src.evaluation.continual import _merge_write
from src.ingestion.loader import load_flows
from src.utils.selection import apply_selection
from tests.conftest import synthetic_raw_csv


def _write_selections(cfg, tmp_path):
    base = tmp_path / "results" / "cicids2017" / "multiclass"
    (base / "tuning").mkdir(parents=True)
    (base / "ewc_lambda_sweep").mkdir(parents=True)
    (base / "tuning" / "selected.yaml").write_text(yaml.safe_dump({"overrides": ["train.gnn_epochs=7"]}))
    (base / "ewc_lambda_sweep" / "selected.json").write_text(json.dumps(
        {"gnn_ewc_replay": {"lambda": 10.0, "gamma": 0.9}, "gnn_ewc": {"lambda": 1000.0, "gamma": 1.0}}))


def test_selection_is_per_exact_model_and_cli_wins(cfg, tmp_path):
    _write_selections(cfg, tmp_path)
    out = apply_selection(cfg)
    assert out["train"]["gnn_epochs"] == 7
    assert out["model_overrides"]["gnn_ewc"] == ["ewc.lambda=1000.0", "ewc.gamma=1.0"]
    assert out["model_overrides"]["gnn_ewc_replay"] == ["ewc.lambda=10.0", "ewc.gamma=0.9"]
    assert "ffnn_ewc_replay" not in out["model_overrides"]          # no family fallback
    cli = apply_selection(cfg, cli_overrides=["train.gnn_epochs=2", "ewc.lambda=5"])
    assert cli["train"]["gnn_epochs"] == 2                           # CLI beats tuning file
    assert cli["model_overrides"]["gnn_ewc"] == ["ewc.gamma=1.0"]    # CLI λ not silently replaced


def test_tuning_from_other_dataset(cfg, tmp_path):
    _write_selections(cfg, tmp_path)
    other = dict(cfg, dataset="csecicids2018", tuning_from="cicids2017")
    assert apply_selection(other)["model_overrides"]["gnn_ewc"]


def test_merge_write_replaces_only_rerun_models(tmp_path):
    p = tmp_path / "summary.csv"
    _merge_write(p, pd.DataFrame({"model": ["a", "a", "b"], "v": [1, 2, 3]}))
    _merge_write(p, pd.DataFrame({"model": ["b"], "v": [9]}))
    d = pd.read_csv(p).sort_values(["model", "v"])
    assert d["model"].tolist() == ["a", "a", "b"] and d["v"].tolist() == [1, 2, 9]


def test_flow_sampling_is_label_agnostic(tmp_path):
    path = tmp_path / "day.csv"
    synthetic_raw_csv(path, n_benign=20_000)
    full, _ = load_flows([path], "benign", 1.0, seed=0)
    sampled, stats = load_flows([path], "benign", 0.3, seed=0)
    assert 0.25 < len(sampled) / len(full) < 0.35
    frac = lambda d: (d["category"] != "Benign").mean()
    # attack share is preserved (label-free sampling), unlike benign-only thinning
    assert abs(frac(sampled) - frac(full)) < 0.01
    assert stats[0]["sampled_out"] > 0
