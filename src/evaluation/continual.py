"""Task-sequence evaluation harness (the core comparison table).

Every model is taken through the identical chronological task sequence. After
each task i the model is evaluated on the held-out test windows of EVERY task
(past, current and future), which yields:
  * accuracy / macro-F1 / FPR on the tasks seen so far       (accuracy over time)
  * recall of task 0's attack category on task 0's test data  (retention rate)
  * recall of task i+1's category BEFORE it is trained on     (novel-attack view)
  * the full matrix R[i][j] for BWT / forgetting
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import torch

from src.evaluation.metrics import category_recall, confusion, core_metrics, forgetting_metrics
from src.graph.window_builder import edge_labels
from src.training.learners import BaseLearner, make_learner
from src.utils.config import class_names, num_classes
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed

log = get_logger(__name__)


def predict_graphs(learner: BaseLearner, graphs: list, label_mode: str) -> dict[str, np.ndarray]:
    y_true, y_cat, y_pred, conf, win = [], [], [], [], []
    for g in graphs:
        p = learner.predict_proba(g)
        y_pred.append(p.argmax(1))
        conf.append(p.max(1))
        y_true.append(edge_labels(g, label_mode).numpy())
        y_cat.append(g.y.numpy())
        win.append(np.full(len(p), int(g.window_id)))
    if not graphs:
        empty = np.empty(0, dtype=np.int64)
        return {"y_true": empty, "y_cat": empty, "y_pred": empty, "conf": np.empty(0), "window_id": empty}
    return {"y_true": np.concatenate(y_true), "y_cat": np.concatenate(y_cat), "y_pred": np.concatenate(y_pred),
            "conf": np.concatenate(conf), "window_id": np.concatenate(win)}


def _concat(preds: list[dict]) -> dict:
    return {k: np.concatenate([p[k] for p in preds]) for k in preds[0]}


def save_checkpoint(learner: BaseLearner, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if learner.family == "xgb":
        with open(path.with_suffix(".pkl"), "wb") as fh:
            pickle.dump(learner.model, fh)
        return
    state = {"model": learner.model.state_dict(), "name": learner.name}
    if getattr(learner, "ewc", None) is not None:
        state["ewc"] = learner.ewc.state_dict()
    torch.save(state, path)


def run_task_sequence(cfg: dict, data, model_names: list[str], out_dir: Path,
                      eval_split: str = "test", eval_transforms: dict[str, Callable | None] | None = None,
                      checkpoint_dir: Path | None = None, tasks: list[int] | None = None) -> pd.DataFrame:
    """Run all models through the task sequence; write CSVs into `out_dir`.

    eval_transforms: {mode_name: fn or None}. Each fn is applied to EVAL graphs
    only (IP-remap evaluation). The SAME trained model is scored under every
    mode, so differences are caused by the remap alone, not by retraining noise.
    Training data is never transformed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    device = get_device(cfg["train"]["device"])
    K, mode = num_classes(cfg), cfg["label_mode"]
    cats = cfg["categories"]
    tasks = tasks if tasks is not None else list(range(data.n_tasks))
    task_cat_ids = [cats.index(data.task_categories[t]) for t in tasks]
    node_in = data.graphs(tasks[0], "train")[0].x.shape[1]
    eval_transforms = eval_transforms or {"none": None}

    base_eval = {t: data.graphs(t, eval_split) for t in tasks}
    eval_sets = {ip: (base_eval if fn is None else {t: [fn(g) for g in gs] for t, gs in base_eval.items()})
                 for ip, fn in eval_transforms.items()}

    long_rows, summary_rows = [], []
    for name in model_names:
        set_seed(cfg["seed"])  # identical initial conditions for every model
        learner = make_learner(name, cfg, data.meta["n_features"], K, device, node_in=node_in)
        R = {ip: np.full((len(tasks), len(tasks)), np.nan) for ip in eval_sets}
        conf_dir = out_dir / "confusion" / name
        conf_dir.mkdir(parents=True, exist_ok=True)
        for i, t in enumerate(tasks):
            stats = learner.learn(data.graphs(t, "train"), tag=f"task{t}")
            log.info("[%s] task %d (%s) trained in %.1fs, %d steps, loss %.4f",
                     name, t, data.task_categories[t], stats.seconds, stats.steps, stats.final_loss)
            for ip, eval_graphs in eval_sets.items():
                Rm = R[ip]
                preds = {j: predict_graphs(learner, eval_graphs[tj], mode) for j, tj in enumerate(tasks)}
                key = (name, ip, i, data.task_categories[t])
                for j, tj in enumerate(tasks):
                    p = preds[j]
                    Rm[i, j] = category_recall(p["y_cat"], p["y_pred"], task_cat_ids[j], mode)
                    for metric, value in core_metrics(p["y_true"], p["y_pred"], mode).items():
                        long_rows.append((*key, f"task{tj}", metric, value))
                    long_rows.append((*key, f"task{tj}", "category_recall", Rm[i, j]))

                seen = _concat([preds[j] for j in range(i + 1)])
                m_seen = core_metrics(seen["y_true"], seen["y_pred"], mode)
                for metric, value in m_seen.items():
                    long_rows.append((*key, "seen", metric, value))
                allp = _concat(list(preds.values()))
                for metric, value in core_metrics(allp["y_true"], allp["y_pred"], mode).items():
                    long_rows.append((*key, "all", metric, value))

                m_task0 = core_metrics(preds[0]["y_true"], preds[0]["y_pred"], mode)
                row = {
                    "model": name, "ip_mode": ip, "after_task": i, "task_category": data.task_categories[t],
                    "accuracy_seen": m_seen["accuracy"], "macro_f1_seen": m_seen["macro_f1"],
                    "fpr_seen": m_seen["fpr"], "detection_rate_seen": m_seen["detection_rate"],
                    "retention_rate": Rm[i, 0],
                    "retention_normalised": Rm[i, 0] / Rm[0, 0] if Rm[0, 0] > 0 else np.nan,
                    "task0_accuracy": m_task0["accuracy"], "task0_macro_f1": m_task0["macro_f1"],
                    "current_task_recall": Rm[i, i],
                    "next_task_recall_before_training": Rm[i, i + 1] if i + 1 < len(tasks) else np.nan,
                    "train_seconds": stats.seconds, "train_steps": stats.steps,
                    "ewc_stability_ratio": (stats.extra.get("ewc") or {}).get("stability_ratio"),
                    # the λ/γ this learner ACTUALLY trained with (after per-model overrides)
                    "ewc_lambda": learner.ewc.lam if getattr(learner, "ewc", None) is not None else np.nan,
                    "ewc_gamma": learner.ewc.gamma if getattr(learner, "ewc", None) is not None else np.nan,
                }
                summary_rows.append(row)

                suffix = "" if ip == "none" else f"_{ip}"
                cm = confusion(seen["y_true"], seen["y_pred"], K)
                pd.DataFrame(cm, index=[f"true_{c}" for c in class_names(cfg)],
                             columns=[f"pred_{c}" for c in class_names(cfg)]).to_csv(
                    conf_dir / f"after_task{i}_seen{suffix}.csv")
                if i == len(tasks) - 1 and ip == "none":
                    # final predictions after the last task, for error analysis
                    pd.DataFrame(allp).to_parquet(out_dir / f"final_predictions_{name}.parquet", index=False)
            if checkpoint_dir is not None and (learner.family != "xgb" or i == 0):
                save_checkpoint(learner, checkpoint_dir / f"{name}_after_task{i}.pt")

        for ip, Rm in R.items():
            suffix = "" if ip == "none" else f"_{ip}"
            pd.DataFrame(Rm, index=[f"after_task{i}" for i in range(len(tasks))],
                         columns=[f"task{j}_{data.task_categories[t]}" for j, t in enumerate(tasks)]).to_csv(
                out_dir / f"recall_matrix_{name}{suffix}.csv")
            with open(out_dir / f"forgetting_{name}{suffix}.json", "w", encoding="utf-8") as fh:
                json.dump(forgetting_metrics(Rm), fh, indent=2)
        with open(out_dir / f"train_history_{name}.json", "w", encoding="utf-8") as fh:
            json.dump(getattr(learner, "history", []), fh, indent=2, default=str)
        del learner
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        # write after every model so a crash later does not lose finished results
        _write(out_dir, long_rows, summary_rows)
    return pd.DataFrame(summary_rows)


LONG_COLUMNS = ["model", "ip_mode", "after_task", "after_task_category", "scope", "metric", "value"]


def _merge_write(path: Path, new: pd.DataFrame) -> None:
    """Replace rows of the models in `new`, keep rows of every other model already
    on disk. Lets one model be re-run into an existing results directory, and lets
    several single-model calls share a directory without overwriting each other."""
    if path.exists() and len(new):
        old = pd.read_csv(path)
        if "model" in old:
            new = pd.concat([old[~old["model"].isin(new["model"].unique())], new], ignore_index=True)
    new.to_csv(path, index=False)


def _write(out_dir: Path, long_rows: list, summary_rows: list) -> None:
    _merge_write(out_dir / "metrics_long.csv", pd.DataFrame(long_rows, columns=LONG_COLUMNS))
    _merge_write(out_dir / "summary.csv", pd.DataFrame(summary_rows))
