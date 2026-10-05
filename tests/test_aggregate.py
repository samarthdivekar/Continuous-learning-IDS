import json

import numpy as np
import pandas as pd

from experiments.aggregate_seeds import load, summarise


def _drift_folder(path, seed, f1):
    path.mkdir(parents=True)
    (path / "run_info.json").write_text(json.dumps({"seed": seed}))
    pd.DataFrame([{"model": "gnn_ewc_replay", "policy": "adwin", "retrains": 10 + seed % 2, "drift_flags": 3,
                   "final_macro_f1_seen": f1, "final_fpr_seen": 0.001, "final_retention_rate": 1.0}]
                 ).to_csv(path / "summary.csv", index=False)
    return path


def test_seeds_come_from_each_folders_run_info(tmp_path):
    frames = [load("drift", _drift_folder(tmp_path / f"d{s}", s, f1), None, None)
              for s, f1 in [(42, 0.90), (43, 0.80), (44, 0.70)]]
    s = summarise(pd.concat(frames), ["model", "policy"], ["final_macro_f1_seen", "retrains"])
    r = s.iloc[0]
    assert r["n"] == 3 and r["seeds"] == "42 43 44"
    assert np.isclose(r["final_macro_f1_seen_mean"], 0.80) and np.isclose(r["final_macro_f1_seen_std"], 0.10)
    assert r["final_macro_f1_seen_per_seed"] == "0.9 0.8 0.7"


def test_sweep_keeps_only_requested_seeds_and_the_last_task(tmp_path):
    rows = [{"model": "gnn_replay", "ip_mode": "none", "after_task": t, "seed": s, "macro_f1_seen": 0.5 + t / 10,
             "fpr_seen": 0.0, "retention_rate": 1.0, "accuracy_seen": 1.0} for s in (42, 43, 44, 45) for t in (0, 1)]
    (tmp_path / "c").mkdir()
    pd.DataFrame(rows).to_csv(tmp_path / "c" / "summary_all_seeds.csv", index=False)
    df = load("sweep", tmp_path / "c", "10", [42, 43, 44])
    assert sorted(df["seed"]) == [42, 43, 44] and set(df["after_task"]) == {1} and set(df["setting"]) == {"10"}


def test_single_seed_has_no_std():
    df = pd.DataFrame([{"model": "m", "policy": "p", "seed": 42, "x": 1.0}])
    assert np.isnan(summarise(df, ["model", "policy"], ["x"]).iloc[0]["x_std"])
