"""Core comparison: every model through the identical chronological task sequence.

    python -m experiments.run_continual --dataset cicids2017 --label-mode multiclass --seeds 42 43 44

Per seed:   results/<dataset>/<label_mode>/continual/seed<k>/...
Aggregate:  results/<dataset>/<label_mode>/continual/summary.csv       (mean over seeds)
            results/<dataset>/<label_mode>/continual/summary_std.csv   (std over seeds)
            results/<dataset>/<label_mode>/continual/summary_all_seeds.csv
            results/<dataset>/<label_mode>/continual/recall_matrix_<model>.csv (mean)
Checkpoints of the first seed go to cache/checkpoints/<dataset>/<label_mode>/ (used by the API).

If results/<dataset>/<label_mode>/ewc_lambda_sweep/selected.json exists, the
validation-selected λ/γ are applied per model (reported in run_info.json).
"""
import json
import shutil

import pandas as pd

from experiments.common import base_parser, config_from_args, results_dir, selected_ewc_overrides
from src.evaluation.continual import run_task_sequence
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import set_seed, write_run_info

log = get_logger("continual")

DEFAULT_MODELS = ["xgboost_static", "gnn_naive", "gnn_ewc_replay", "ffnn_ewc_replay",
                  "ffnn_naive", "gnn_ewc", "gnn_replay", "gnn_joint", "ffnn_joint"]


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    p.add_argument("--seeds", nargs="*", type=int, default=[42])
    p.add_argument("--split", default="test", choices=["test", "val"])
    p.add_argument("--no-selected", action="store_true", help="ignore validation-selected EWC settings")
    args = p.parse_args()
    base_cfg = config_from_args(args)
    prepare_dataset(base_cfg)
    data = load_processed(base_cfg)
    root = results_dir(base_cfg, args, "continual" if args.split == "test" else "continual_val")
    root.mkdir(parents=True, exist_ok=True)
    sel = {"source": None, "overrides": {}} if args.no_selected else selected_ewc_overrides(base_cfg, args)

    summaries = []
    for i, seed in enumerate(args.seeds):
        cfg = apply_overrides(base_cfg, [f"seed={seed}"])
        cfg["model_overrides"] = sel["overrides"]
        set_seed(seed)
        out = root / f"seed{seed}"
        write_run_info(out / "run_info.json", cfg, {
            "models": args.models, "eval_split": args.split, "task_categories": data.task_categories,
            "ewc_selection": sel,
            "data_meta": {k: data.meta[k] for k in ("n_flows", "n_windows", "n_features", "cache_key")}})
        ckpt = None
        if i == 0 and args.split == "test" and not args.dev:
            ckpt = resolve_path(cfg, "checkpoints") / cfg["dataset"] / cfg["label_mode"]
        s = run_task_sequence(cfg, data, args.models, out, eval_split=args.split, checkpoint_dir=ckpt)
        s["seed"] = seed
        summaries.append(s)

    allseeds = pd.concat(summaries, ignore_index=True)
    allseeds.to_csv(root / "summary_all_seeds.csv", index=False)
    keys = ["model", "ip_mode", "after_task", "task_category"]
    num = allseeds.drop(columns=["seed"]).select_dtypes("number").columns.difference(["after_task"])
    grouped = allseeds.groupby(keys, sort=False)[list(num)]
    mean = grouped.mean().reset_index()
    mean["n_seeds"] = len(args.seeds)
    mean.to_csv(root / "summary.csv", index=False)
    grouped.std(ddof=1).reset_index().to_csv(root / "summary_std.csv", index=False)
    for model in args.models:
        mats = [pd.read_csv(root / f"seed{s}" / f"recall_matrix_{model}.csv", index_col=0) for s in args.seeds]
        (sum(mats) / len(mats)).to_csv(root / f"recall_matrix_{model}.csv")
    first = root / f"seed{args.seeds[0]}" / "run_info.json"
    shutil.copy(first, root / "run_info.json")
    with open(root / "seeds.json", "w", encoding="utf-8") as fh:
        json.dump({"seeds": args.seeds}, fh)

    last = mean[mean["after_task"] == mean["after_task"].max()]
    cols = ["model", "accuracy_seen", "macro_f1_seen", "retention_rate", "fpr_seen"]
    print(f"Final (after last task), mean over seeds {args.seeds}:")
    print(last[cols].to_string(index=False))


if __name__ == "__main__":
    main()
