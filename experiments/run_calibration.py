"""Calibration of the final continual models, beside the conformal results.

    python -m experiments.run_calibration --dataset cicids2017

Uses the same inputs as run_conformal: the checkpoints saved after the LAST task (run_continual,
first seed) and the test windows of all tasks. Reports, per model, ECE / MCE / Brier on all test
flows and separately on attack and benign flows, plus a reliability diagram.
Outputs: results/<ds>/multiclass/calibration/{calibration.csv, reliability.csv, reliability.png, run_info.json}
"""
import numpy as np
import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from experiments.run_conformal import gather
from src.evaluation.calibration import calibration_errors, reliability
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import load_learner_checkpoint, make_learner
from src.utils.config import num_classes, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info

log = get_logger("calibration")
LABELS = {"gnn_ewc_replay": "GNN + EWC + replay (ours)", "ffnn_ewc_replay": "FFNN + EWC + replay (ablation)"}


def plot(rel: pd.DataFrame, summary: pd.DataFrame, path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    models = list(dict.fromkeys(rel["model"]))
    fig, axes = plt.subplots(2, len(models), figsize=(5 * len(models), 6.5), squeeze=False,
                             gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    for j, m in enumerate(models):
        r = rel[(rel["model"] == m) & (rel["n"] > 0)]
        ece = summary[(summary["model"] == m) & (summary["flows"] == "all")]["ece"].iloc[0]
        ax = axes[0, j]
        ax.plot([0, 1], [0, 1], ls="--", c="grey", lw=1, label="perfect calibration")
        ax.bar(r["lower"], r["accuracy"], width=r["upper"] - r["lower"], align="edge",
               edgecolor="black", alpha=0.75, label="accuracy in bin")
        ax.plot(r["confidence"], r["accuracy"], "o", c="black", ms=3)
        ax.set_title(f"{LABELS.get(m, m)}\nECE {ece:.4f}", fontsize=10)
        ax.set_ylabel("accuracy")
        ax.set_ylim(0, 1)
        ax.legend(loc="upper left", fontsize=8)
        cnt = axes[1, j]
        cnt.bar(r["lower"], r["n"], width=r["upper"] - r["lower"], align="edge", edgecolor="black")
        cnt.set_yscale("log")
        cnt.set_xlabel("confidence (max class probability)")
        cnt.set_ylabel("flows (log)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=["gnn_ewc_replay", "ffnn_ewc_replay"])
    p.add_argument("--bins", type=int, default=15)
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    set_seed(cfg["seed"])
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "calibration")
    out.mkdir(parents=True, exist_ok=True)
    write_run_info(out / "run_info.json", cfg, {"models": args.models, "bins": args.bins,
                                                  "checkpoints": "after the last task, first seed of run_continual",
                                                  "test": "test windows of all tasks"})
    device = get_device(cfg["train"]["device"])
    ckpt = resolve_path(cfg, "checkpoints") / cfg["dataset"] / cfg["label_mode"]
    last = data.n_tasks - 1
    test = [g for t in range(data.n_tasks) for g in data.graphs(t, "test")]
    summary, rel = [], []
    for model in args.models:
        learner = load_learner_checkpoint(make_learner(model, cfg, data.meta["n_features"], num_classes(cfg), device,
                                                       node_in=data.graphs(0, "train")[0].x.shape[1]),
                                          ckpt / f"{model}_after_task{last}.pt")
        probs, y = gather(learner, test)
        attack = y != 0
        for flows, mask in (("all", np.ones_like(attack)), ("attack", attack), ("benign", ~attack)):
            summary.append({"model": model, "flows": flows, **calibration_errors(probs[mask], y[mask], args.bins)})
        rel += [{"model": model, **r} for r in reliability(probs, y, args.bins)]
        log.info("%s ECE all %.4f attack %.4f benign %.4f", model, *[s["ece"] for s in summary[-3:]])
    summary, rel = pd.DataFrame(summary), pd.DataFrame(rel)
    summary.to_csv(out / "calibration.csv", index=False)
    rel.to_csv(out / "reliability.csv", index=False)
    plot(rel, summary, out / "reliability.png")
    print(summary.round(5).to_string(index=False))


if __name__ == "__main__":
    main()
