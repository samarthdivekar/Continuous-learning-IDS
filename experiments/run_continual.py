"""Core comparison: every model through the identical chronological task sequence.

    python -m experiments.run_continual --dataset cicids2017 --label-mode multiclass --seeds 42 43 44

Per seed:   results/<dataset>/<label_mode>/continual/seed<k>/...
Aggregate:  results/<dataset>/<label_mode>/continual/summary.csv       (mean over seeds)
            results/<dataset>/<label_mode>/continual/summary_std.csv   (std over seeds)
            results/<dataset>/<label_mode>/continual/summary_all_seeds.csv
            results/<dataset>/<label_mode>/continual/recall_matrix_<model>.csv (mean)
Checkpoints of the first seed go to cache/checkpoints/<dataset>/<label_mode>/ (used by the API).

Validation selections (tuning/selected.yaml, per-model ewc_lambda_sweep/selected.json)
are applied unless --no-selected; CLI --set values always take precedence. The λ/γ
each model actually trained with is written to the summary rows.

Running a subset of models (e.g. --models gnn_ewc) MERGES into existing seed
directories: rows of the re-run models are replaced, other models are kept, and
the aggregate is recomputed over every model present.
"""
import json
import shutil

import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.evaluation.continual import run_task_sequence
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import set_seed, write_run_info

log = get_logger("continual")

DEFAULT_MODELS = ["xgboost_static", "gnn_naive", "gnn_ewc_replay", "ffnn_ewc_replay",
                  "ffnn_naive", "gnn_ewc", "gnn_replay", "gnn_joint", "ffnn_joint"]


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
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    p.add_argument("--seeds", nargs="*", type=int, default=[42])
    p.add_argument("--split", default="test", choices=["test", "val"])
    p.add_argument("--no-selected", action="store_true", help="ignore validation-selected settings")
    args = p.parse_args()
    base_cfg = config_from_args(args) if args.no_selected else apply_selection(config_from_args(args), args)
    prepare_dataset(base_cfg)
    data = load_processed(base_cfg)
    root = results_dir(base_cfg, args, "continual" if args.split == "test" else "continual_val")
    root.mkdir(parents=True, exist_ok=True)

    for i, seed in enumerate(args.seeds):
        cfg = apply_overrides(base_cfg, [f"seed={seed}"])
        set_seed(seed)
        out = root / f"seed{seed}"
        info_name = "run_info.json" if not (out / "run_info.json").exists() or set(args.models) == set(DEFAULT_MODELS) \
            else f"run_info_{'_'.join(args.models)}.json"
        write_run_info(out / info_name, cfg, {
            "models": args.models, "eval_split": args.split, "task_categories": data.task_categories,
            "data_meta": {k: data.meta[k] for k in ("n_flows", "n_windows", "n_features", "cache_key")}})
        ckpt = None
        if i == 0 and args.split == "test" and not args.dev:
            ckpt = resolve_path(cfg, "checkpoints") / cfg["dataset"] / cfg["label_mode"]
        run_task_sequence(cfg, data, args.models, out, eval_split=args.split, checkpoint_dir=ckpt)

    seeds_on_disk = sorted({int(d.name[4:]) for d in root.glob("seed*") if d.is_dir()} | set(args.seeds))
    mean = aggregate(root, seeds_on_disk)
    first = root / f"seed{seeds_on_disk[0]}" / "run_info.json"
    if first.exists():
        shutil.copy(first, root / "run_info.json")
    last = mean[(mean["after_task"] == mean["after_task"].max()) & (mean["ip_mode"] == "none")]
    cols = ["model", "n_seeds", "accuracy_seen", "macro_f1_seen", "retention_rate", "fpr_seen"]
    print(f"Final (after last task), mean over seeds {seeds_on_disk}:")
    print(last[cols].to_string(index=False))


if __name__ == "__main__":
    main()
