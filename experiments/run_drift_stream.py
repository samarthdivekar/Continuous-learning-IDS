"""Phase 7: ADWIN-triggered adaptation on a chronological stream.

    python -m experiments.run_drift_stream --dataset cicids2017

For each (model, policy) pair: stream the windows of tasks 1..T-1, adapt
according to the policy, and log per-window predictions/errors, drift events
and periodic evaluations. Compares retrain counts and final quality of
  adwin (ours) vs periodic vs oracle (true task boundaries) vs never.
"""
import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.evaluation.stream import StreamRunner
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import make_learner
from src.utils.config import num_classes
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info

log = get_logger("drift")

DEFAULT_RUNS = [
    ("gnn_ewc_replay", "adwin"), ("gnn_ewc_replay", "periodic"), ("gnn_ewc_replay", "oracle"),
    ("gnn_ewc_replay", "never"), ("gnn_naive", "adwin"), ("ffnn_ewc_replay", "adwin"),
    ("xgboost_static", "never"),
]


def main():
    p = base_parser(__doc__)
    p.add_argument("--runs", nargs="*", default=[f"{m}:{pol}" for m, pol in DEFAULT_RUNS],
                   help="model:policy pairs")
    p.add_argument("--eval-every", type=int, default=10)
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "drift")
    out.mkdir(parents=True, exist_ok=True)
    write_run_info(out / "run_info.json", cfg, {"runs": args.runs, "task_categories": data.task_categories})
    device = get_device(cfg["train"]["device"])
    node_in = data.graphs(0, "train")[0].x.shape[1]

    windows, evals, events, summary = [], [], [], []
    for run in args.runs:
        model, policy = run.split(":")
        set_seed(cfg["seed"])
        learner = make_learner(model, cfg, data.meta["n_features"], num_classes(cfg), device, node_in=node_in)
        runner = StreamRunner(cfg, data, learner, policy=policy, eval_every=args.eval_every)
        log.info("stream: %s / %s", model, policy)
        runner.run()
        w, e, d = runner.frames()
        windows.append(w)
        evals.append(e)
        if len(d):
            d["policy"] = policy
            events.append(d)
        final = e.iloc[-1]
        n_boundaries = int((w["task_id"].diff().fillna(0) != 0).sum())
        summary.append({
            "model": model, "policy": policy, "stream_windows": len(w), "retrains": runner.retrains,
            "true_task_boundaries": n_boundaries,
            "drift_flags": int(w["drift_flag"].sum()),
            "final_accuracy_seen": final["accuracy_seen"], "final_macro_f1_seen": final["macro_f1_seen"],
            "final_retention_rate": final["retention_rate"], "final_fpr_seen": final["fpr_seen"],
            "mean_stream_error": w["error_rate"].mean(),
        })
        pd.concat(windows).to_csv(out / "stream_windows.csv", index=False)
        pd.concat(evals).to_csv(out / "stream_eval.csv", index=False)
        if events:
            pd.concat(events).to_csv(out / "drift_events.csv", index=False)
        pd.DataFrame(summary).to_csv(out / "summary.csv", index=False)
    print(pd.DataFrame(summary).to_string(index=False))


if __name__ == "__main__":
    main()
