"""Combine single-seed result folders into one multi-seed table.

    python -m experiments.aggregate_seeds loao   --dataset csecicids2018 --label-mode binary \
        --folders loao loao_seed43 loao_seed44 --out loao_seeds
    python -m experiments.aggregate_seeds drift  --folders drift_seed42 drift_seed43 drift_seed44 --out drift_seeds
    python -m experiments.aggregate_seeds ipremap --folders ip_remap ip_remap_seed43 ip_remap_seed44 --out ip_remap_seeds
    python -m experiments.aggregate_seeds sweep  --folders replay_budget_0 replay_budget_1 replay_budget_5 continual \
        replay_budget_20 --labels 0 1 5 10 20 --seeds 42 43 44 --out replay_budget_sweep

Each folder's seed is read from its own run_info.json (sweep folders hold several seeds and use the
per-row `seed` column instead), so a folder is never counted under the wrong seed and two folders with
the same seed are refused. Per group the table gives n, mean, std, min, max and the per-seed values.

  loao     key (held-out category, model)  — detection rate, FPR, binary F1
  drift    key (model, policy)             — retrains, drift flags, final macro-F1, FPR, retention
  ipremap  key (model, IP mode)            — macro-F1 and FPR after the last task
  sweep    key (setting, model)            — last-task macro-F1, FPR, retention and accuracy from
                                             run_continual folders (one setting per folder, --labels)

Output: results/<dataset>/<mode>/<out>/{summary.csv, per_seed.csv}
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from src.utils.config import REPO_ROOT

KINDS = {
    "loao": (["held_out_category", "model"], ["heldout_detection_rate", "fpr", "binary_f1"]),
    "drift": (["model", "policy"], ["retrains", "drift_flags", "final_macro_f1_seen", "final_fpr_seen",
                                    "final_retention_rate"]),
    "ipremap": (["model", "ip_mode"], ["macro_f1_seen", "fpr_seen"]),
    "sweep": (["setting", "model"], ["macro_f1_seen", "fpr_seen", "retention_rate", "accuracy_seen"]),
}


def folder_seed(path) -> int:
    return int(json.loads((path / "run_info.json").read_text(encoding="utf-8"))["seed"])


def load(kind: str, path, label: str | None, seeds: list[int] | None) -> pd.DataFrame:
    if kind == "loao":
        df = pd.read_csv(path / "loao.csv").assign(seed=folder_seed(path))
    elif kind == "drift":
        df = pd.read_csv(path / "summary.csv").assign(seed=folder_seed(path))
    elif kind == "ipremap":
        df = pd.read_csv(path / "summary.csv")
        df = df[df["after_task"] == df["after_task"].max()].assign(seed=folder_seed(path))
    else:
        df = pd.read_csv(path / "summary_all_seeds.csv")
        if "ip_mode" in df:
            df = df[df["ip_mode"] == "none"]
        df = df[df["after_task"] == df["after_task"].max()].assign(setting=label)
        if seeds:
            df = df[df["seed"].isin(seeds)]
    return df


def summarise(per_seed: pd.DataFrame, keys: list[str], metrics: list[str]) -> pd.DataFrame:
    rows = []
    for key, g in per_seed.groupby(keys, sort=False):
        g = g.sort_values("seed")
        row = dict(zip(keys, key if isinstance(key, tuple) else (key,)))
        row["n"] = len(g)
        row["seeds"] = " ".join(str(int(s)) for s in g["seed"])
        for m in metrics:
            v = g[m].to_numpy(dtype=float)
            row.update({f"{m}_mean": np.nanmean(v), f"{m}_std": np.nanstd(v, ddof=1) if len(v) > 1 else np.nan,
                        f"{m}_min": np.nanmin(v), f"{m}_max": np.nanmax(v),
                        f"{m}_per_seed": " ".join(f"{x:.4g}" for x in v)})
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("kind", choices=list(KINDS))
    p.add_argument("--dataset", default="cicids2017")
    p.add_argument("--label-mode", default="multiclass")
    p.add_argument("--folders", nargs="+", required=True)
    p.add_argument("--labels", nargs="*", help="sweep: one setting label per folder")
    p.add_argument("--seeds", nargs="*", type=int, help="sweep: keep only these seeds")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    keys, metrics = KINDS[args.kind]
    base = REPO_ROOT / "results" / args.dataset / args.label_mode
    if args.kind == "sweep" and (not args.labels or len(args.labels) != len(args.folders)):
        p.error("sweep needs one --labels entry per folder")
    frames = [load(args.kind, base / f, (args.labels or [None] * len(args.folders))[i], args.seeds)
              for i, f in enumerate(args.folders)]
    if args.kind != "sweep":
        seeds = [int(f["seed"].iloc[0]) for f in frames]
        if len(set(seeds)) != len(seeds):
            raise SystemExit(f"two folders share a seed: {dict(zip(args.folders, seeds))}")
    per_seed = pd.concat(frames, ignore_index=True)
    out = base / args.out
    out.mkdir(parents=True, exist_ok=True)
    per_seed.to_csv(out / "per_seed.csv", index=False)
    summary = summarise(per_seed, keys, metrics)
    summary.to_csv(out / "summary.csv", index=False)
    (out / "sources.json").write_text(json.dumps({"kind": args.kind, "folders": args.folders,
                                                  "labels": args.labels, "seeds": args.seeds}, indent=2))
    show = keys + ["n"] + [f"{m}_mean" for m in metrics[:2]] + [f"{m}_std" for m in metrics[:2]]
    print(summary[show].to_string(index=False, float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
