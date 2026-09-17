"""EWC λ / γ sweep (brief §5.3 trap 3), scored on the VALIDATION split.

    python -m experiments.sweep_ewc_lambda --dataset cicids2017 --label-mode multiclass
    python -m experiments.sweep_ewc_lambda --models gnn_ewc          # add a model; merges

Logs, per (λ, γ) and model, the final validation metrics, the maximum
lr·λ·max(F) stability ratio reached, and whether training diverged.

Selection (selected.json, one entry PER EXACT MODEL NAME): highest final
validation macro-F1, ties broken towards smaller λ. Every EWC model that is
reported is swept itself, so an ablation never inherits a λ tuned for a
different model. Caveat recorded in the README: validation macro-F1 is driven
by very small classes (WebAttack, Botnet) and GNN training is not bit-exact on
CUDA, so neighbouring λ values are often within run-to-run noise.

Outputs merge: re-running a subset of models replaces only their rows in
sweep.csv and their entries in selected.json.
"""
import json

import pandas as pd

from experiments.common import apply_tuning, base_parser, config_from_args, results_dir
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
    p.add_argument("--models", nargs="*", default=["gnn_ewc_replay", "ffnn_ewc_replay", "gnn_ewc"])
    args = p.parse_args()
    base = apply_tuning(config_from_args(args), args)
    prepare_dataset(base)
    data = load_processed(base)
    out = results_dir(base, args, "ewc_lambda_sweep")
    out.mkdir(parents=True, exist_ok=True)
    write_run_info(out / f"run_info_{'_'.join(args.models)}.json", base,
                   {"lambdas": args.lambdas, "gammas": args.gammas, "models": args.models, "split": "val"})
    old = pd.read_csv(out / "sweep.csv") if (out / "sweep.csv").exists() else pd.DataFrame()
    if len(old):
        old = old[~old["model"].isin(args.models)]
    rows = []
    for gamma in args.gammas:
        for lam in args.lambdas:
            cfg = apply_overrides(base, [f"ewc.lambda={lam}", f"ewc.gamma={gamma}"])
            for model in args.models:
                sub = out / f"gamma_{gamma:g}_lambda_{lam:g}" / model
                row = {"lambda": lam, "gamma": gamma, "model": model, "lr_times_lambda": cfg["train"]["lr"] * lam}
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
                pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(out / "sweep.csv", index=False)
    df = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    ok = df[~df["diverged"].astype(bool)]
    best = json.loads((out / "selected.json").read_text()) if (out / "selected.json").exists() else {}
    for model, g in ok[ok["model"].isin(args.models)].groupby("model"):
        b = g.sort_values(["val_macro_f1_seen", "lambda"], ascending=[False, True]).iloc[0]
        best[model] = {"lambda": float(b["lambda"]), "gamma": float(b["gamma"])}
    with open(out / "selected.json", "w", encoding="utf-8") as fh:
        json.dump(dict(sorted(best.items())), fh, indent=2)
    print(df.to_string(index=False))
    print("selected:", best)


if __name__ == "__main__":
    main()
