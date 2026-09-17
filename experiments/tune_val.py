"""Small, symmetric hyper-parameter check on the VALIDATION split.

    python -m experiments.tune_val --dataset cicids2017

Both continual model families get the same grid size (epochs per task, and for
the GNN the replay-loss balancing switch that mirrors the FFNN's balanced row
sampling). Selection criterion: final validation macro-F1 over all seen tasks.
Test windows are never touched here. The chosen values are written to
results/<dataset>/<label_mode>/tuning/selected.yaml and used by reproduce_all.
"""
import pandas as pd
import yaml

from experiments.common import base_parser, config_from_args, results_dir
from src.evaluation.continual import run_task_sequence
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides
from src.utils.repro import write_run_info

GRID = {
    "gnn_ewc_replay": [
        ["train.gnn_epochs=3", "replay.category_balanced_loss=false"],
        ["train.gnn_epochs=3", "replay.category_balanced_loss=true"],
        ["train.gnn_epochs=10", "replay.category_balanced_loss=false"],
        ["train.gnn_epochs=10", "replay.category_balanced_loss=true"],
    ],
    "ffnn_ewc_replay": [
        ["train.ffnn_epochs=3"], ["train.ffnn_epochs=5"], ["train.ffnn_epochs=10"], ["train.ffnn_epochs=20"],
    ],
}


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    base = config_from_args(args)
    prepare_dataset(base)
    data = load_processed(base)
    out = results_dir(base, args, "tuning")
    out.mkdir(parents=True, exist_ok=True)
    write_run_info(out / "run_info.json", base, {"grid": GRID, "split": "val", "criterion": "final macro_f1_seen"})
    rows, selected = [], {}
    for model, grid in GRID.items():
        best = None
        for k, overrides in enumerate(grid):
            cfg = apply_overrides(base, overrides)
            s = run_task_sequence(cfg, data, [model], out / f"{model}_{k}", eval_split="val")
            last = s.iloc[-1]
            row = {"model": model, "overrides": " ".join(overrides), "val_macro_f1_seen": last["macro_f1_seen"],
                   "val_accuracy_seen": last["accuracy_seen"], "val_retention_rate": last["retention_rate"],
                   "val_fpr_seen": last["fpr_seen"], "mean_macro_f1_over_tasks": s["macro_f1_seen"].mean()}
            rows.append(row)
            pd.DataFrame(rows).to_csv(out / "tuning.csv", index=False)
            if best is None or row["val_macro_f1_seen"] > best[0] + 1e-9:
                best = (row["val_macro_f1_seen"], overrides)
        selected[model] = best[1]
    # shared keys: each family owns its own epoch key, so the selections do not collide
    merged = sorted({o for ov in selected.values() for o in ov})
    with open(out / "selected.yaml", "w", encoding="utf-8") as fh:
        yaml.safe_dump({"per_model": selected, "overrides": merged}, fh)
    print(pd.DataFrame(rows).to_string(index=False))
    print("selected:", selected)


if __name__ == "__main__":
    main()
