"""Calibrated abstention (improvement 4) on the final continual models.

    python -m experiments.run_conformal --dataset cicids2017

Uses the checkpoints saved after the LAST task (run_continual, first seed).
Calibration: validation windows of all tasks. Test: test windows of all tasks.
Reports, per model and α: coverage, abstention rate, accuracy on the flows the
system acts on, and how many argmax false alarms abstention removes.
Outputs: results/<ds>/multiclass/conformal/{conformal.csv, per_class.csv, run_info.json}
"""
import numpy as np
import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.evaluation.conformal import evaluate, fit_class_thresholds, prediction_sets
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import load_learner_checkpoint, make_learner
from src.utils.config import num_classes, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info

log = get_logger("conformal")


def gather(learner, graphs):
    P, Y = [], []
    for g in graphs:
        P.append(learner.predict_proba(g)); Y.append(g.y.numpy())
    return np.concatenate(P), np.concatenate(Y)


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=["gnn_ewc_replay", "ffnn_ewc_replay"])
    p.add_argument("--alphas", nargs="*", type=float, default=[0.01, 0.05, 0.10])
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    set_seed(cfg["seed"])
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "conformal")
    write_run_info(out / "run_info.json", cfg, {"models": args.models, "alphas": args.alphas,
                                                  "calibration": "val windows of all tasks", "test": "test windows of all tasks"})
    device = get_device(cfg["train"]["device"])
    ckpt = resolve_path(cfg, "checkpoints") / cfg["dataset"] / cfg["label_mode"]
    last = data.n_tasks - 1
    cats = cfg["categories"]
    rows, per_class = [], []
    for model in args.models:
        learner = load_learner_checkpoint(make_learner(model, cfg, data.meta["n_features"], num_classes(cfg), device,
                                                       node_in=data.graphs(0, "train")[0].x.shape[1]),
                                          ckpt / f"{model}_after_task{last}.pt")
        pc, yc = gather(learner, [g for t in range(data.n_tasks) for g in data.graphs(t, "val")])
        pt, yt = gather(learner, [g for t in range(data.n_tasks) for g in data.graphs(t, "test")])
        for a in args.alphas:
            q = fit_class_thresholds(pc, yc, a)
            fallback = max(q.values())            # rare classes without enough calibration flows: most permissive
            sets = prediction_sets(pt, q, fallback)
            m = evaluate(pt, yt, sets)
            m.update({"model": model, "alpha": a, "classes_calibrated": len(q)})
            rows.append(m)
            log.info("%s α=%.2f coverage %.4f abstain %.4f FA %d -> %d", model, a, m["coverage"], m["abstain_rate"],
                     m["false_alarms_argmax"], m["false_alarms_after_abstention"])
            size = sets.sum(1)
            for c in np.unique(yt):
                idx = yt == c
                per_class.append({"model": model, "alpha": a, "category": cats[c], "n": int(idx.sum()),
                                  "coverage": float(sets[idx, c].mean()), "abstain_rate": float((size[idx] != 1).mean()),
                                  "threshold": q.get(int(c))})
        pd.DataFrame(rows).to_csv(out / "conformal.csv", index=False)
        pd.DataFrame(per_class).to_csv(out / "per_class.csv", index=False)
    print(pd.DataFrame(rows)[["model", "alpha", "coverage", "abstain_rate", "accuracy_acted", "false_alarms_argmax",
                               "false_alarms_after_abstention", "attack_abstain_rate"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
