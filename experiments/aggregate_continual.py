"""Cross-seed aggregation of a run_continual results folder (pure pandas, no torch).

    python -m experiments.aggregate_continual --dataset cicids2017 --label-mode multiclass --name continual_temporal

run_continual calls `aggregate` at the end of every run. This entry point re-aggregates a folder from the
seed folders already on disk, e.g. after a run was interrupted: it reads seed*/summary.csv only, so a seed
that is missing a model simply contributes no row for that model (`n_seeds` says how many did).
Writes summary_all_seeds.csv, summary.csv (mean), summary_std.csv, recall_matrix_<model>.csv (mean) and
seeds.json into the folder.
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from src.utils.config import REPO_ROOT


def aggregate(root, seeds: list[int]) -> pd.DataFrame:
    per_seed = []
    for s in seeds:
        f = root / f"seed{s}" / "summary.csv"
        if f.exists():
            d = pd.read_csv(f)
            d["seed"] = s
            per_seed.append(d)
    allseeds = pd.concat(per_seed, ignore_index=True)
    allseeds.to_csv(root / "summary_all_seeds.csv", index=False)
    keys = ["model", "ip_mode", "after_task", "task_category"]
    num = allseeds.drop(columns=["seed"]).select_dtypes("number").columns.difference(["after_task"])
    grouped = allseeds.groupby(keys, sort=False)[list(num)]
    mean = grouped.mean().reset_index()
    mean = mean.merge(allseeds.groupby("model")["seed"].nunique().rename("n_seeds").reset_index(), on="model")
    mean.to_csv(root / "summary.csv", index=False)
    grouped.std(ddof=1).reset_index().to_csv(root / "summary_std.csv", index=False)
    for model in allseeds["model"].unique():
        mats = [pd.read_csv(root / f"seed{s}" / f"recall_matrix_{model}.csv", index_col=0)
                for s in seeds if (root / f"seed{s}" / f"recall_matrix_{model}.csv").exists()]
        (sum(mats) / len(mats)).to_csv(root / f"recall_matrix_{model}.csv")
    with open(root / "seeds.json", "w", encoding="utf-8") as fh:
        json.dump({"seeds": seeds}, fh)
    return mean


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="cicids2017")
    p.add_argument("--label-mode", default="multiclass")
    p.add_argument("--name", default="continual")
    args = p.parse_args()
    root = REPO_ROOT / "results" / args.dataset / args.label_mode / args.name
    seeds = sorted(int(d.name[4:]) for d in root.glob("seed*") if d.is_dir())
    mean = aggregate(root, seeds)
    first = root / f"seed{seeds[0]}" / "run_info.json"
    if first.exists():
        (root / "run_info.json").write_bytes(first.read_bytes())
    last = mean[(mean["after_task"] == mean["after_task"].max()) & (mean["ip_mode"] == "none")]
    print(f"Final (after last task), mean over seeds {seeds}:")
    print(last[["model", "n_seeds", "macro_f1_seen", "retention_rate", "fpr_seen"]].to_string(index=False))


if __name__ == "__main__":
    main()
