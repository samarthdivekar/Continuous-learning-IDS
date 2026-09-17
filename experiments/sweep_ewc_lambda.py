"""EWC λ sweep (brief §5.3 trap 3), scored on the VALIDATION split.

    python -m experiments.sweep_ewc_lambda --dataset cicids2017 --lambdas 0 1 10 100 1000 10000

Logs, per λ and model, the final validation metrics and the maximum
lr·λ·max(F) stability ratio reached, plus whether training diverged.
The λ used for the reported test results is chosen from this file by
experiments/reproduce_all.py (highest final val macro-F1, ties -> smaller λ).
"""
import json

import pandas as pd

from experiments.common import base_parser, config_from_args, results_dir
from src.evaluation.continual import run_task_sequence
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides
from src.utils.logging import get_logger
from src.utils.repro import write_run_info

log = get_logger("sweep")


def main():
    p = base_parser(__doc__)
    p.add_argument("--lambdas", nargs="*", type=float, default=[1, 10, 100, 1000, 10000])
    p.add_argument("--gammas", nargs="*", type=float, default=[1.0, 0.9])
    p.add_argument("--models", nargs="*", default=["gnn_ewc_replay", "ffnn_ewc_replay"])
    args = p.parse_args()
    base = config_from_args(args)
    prepare_dataset(base)
    data = load_processed(base)
    out = results_dir(base, args, "ewc_lambda_sweep")
    out.mkdir(parents=True, exist_ok=True)
    write_run_info(out / "run_info.json", base, {"lambdas": args.lambdas, "gammas": args.gammas,
                                                  "models": args.models, "split": "val"})
    rows = []
    for gamma in args.gammas:
        for lam in args.lambdas:
            cfg = apply_overrides(base, [f"ewc.lambda={lam}", f"ewc.gamma={gamma}"])
            for model in args.models:
                sub = out / f"gamma_{gamma:g}_lambda_{lam:g}"
                row = {"lambda": lam, "gamma": gamma, "model": model,
                       "lr_times_lambda": cfg["train"]["lr"] * lam}
                try:
                    s = run_task_sequence(cfg, data, [model], sub, eval_split="val")
                    last = s.iloc[-1]
                    row.update({"diverged": False, "val_accuracy_seen": last["accuracy_seen"],
                                "val_macro_f1_seen": last["macro_f1_seen"],
                                "val_retention_rate": last["retention_rate"], "val_fpr_seen": last["fpr_seen"],
                                "mean_val_macro_f1_over_tasks": s["macro_f1_seen"].mean(),
                                "max_stability_ratio": s["ewc_stability_ratio"].max()})
                except FloatingPointError as exc:
                    log.warning("lambda=%g gamma=%g %s diverged: %s", lam, gamma, model, exc)
                    row["diverged"] = True
                rows.append(row)
                pd.DataFrame(rows).to_csv(out / "sweep.csv", index=False)
    df = pd.DataFrame(rows)
    ok = df[~df["diverged"]]
    best = {}
    for model, g in ok.groupby("model"):
        # highest final val macro-F1; ties broken towards smaller lambda (weaker constraint)
        b = g.sort_values(["val_macro_f1_seen", "lambda"], ascending=[False, True]).iloc[0]
        best[model] = {"lambda": float(b["lambda"]), "gamma": float(b["gamma"])}
    with open(out / "selected.json", "w", encoding="utf-8") as fh:
        json.dump(best, fh, indent=2)
    print(df.to_string(index=False))
    print("selected:", best)


if __name__ == "__main__":
    main()
