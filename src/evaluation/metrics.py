"""Metric definitions (brief §6). All metrics are computed from raw prediction
arrays so every number in results/ can be recomputed from saved predictions.

Definitions
-----------
accuracy          fraction of flows whose predicted class == true class
macro_f1          unweighted mean F1 over classes present in y_true (sklearn,
                  zero_division=0). Reported with accuracy because benign
                  traffic dominates and makes raw accuracy flattering.
fpr               false-positive rate = benign flows predicted as ANY attack
                  class / all benign flows
detection_rate    attack flows predicted as ANY attack class / all attack flows
                  (binary view, valid in both label modes)
category_recall   per attack category: multiclass -> predicted exactly that
                  category; binary -> predicted "attack"

Continual-learning metrics (computed after each task i)
---------------------------------------------------------
accuracy over time   accuracy / macro-F1 on the union of test windows of all
                     tasks seen so far (0..i)
retention rate       category_recall of the FIRST task's attack category,
                     measured on task 0's test windows, after every task i.
                     (Task-0 test windows are >99% benign, so plain task-0
                     accuracy would hide forgetting; we report it as well.)
                     `retention_normalised` = retention_i / retention_0.
forgetting / BWT     from the matrix R[i][j] = category_recall of task j's
                     category after training task i (Lopez-Paz & Ranzato 2017)
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import confusion_matrix, f1_score


def binary_view(y: np.ndarray, label_mode: str) -> np.ndarray:
    return (y > 0).astype(np.int64) if label_mode == "multiclass" else y.astype(np.int64)


def core_metrics(y_true: np.ndarray, y_pred: np.ndarray, label_mode: str) -> dict:
    if len(y_true) == 0:
        return {"n": 0}
    yt_b, yp_b = binary_view(y_true, label_mode), binary_view(y_pred, label_mode)
    benign = yt_b == 0
    attack = ~benign
    labels = np.unique(y_true)
    return {
        "n": int(len(y_true)),
        "n_benign": int(benign.sum()),
        "n_attack": int(attack.sum()),
        "accuracy": float((y_true == y_pred).mean()),
        "macro_f1": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "fpr": float((yp_b[benign] == 1).mean()) if benign.any() else float("nan"),
        "detection_rate": float((yp_b[attack] == 1).mean()) if attack.any() else float("nan"),
        "binary_f1": float(f1_score(yt_b, yp_b, zero_division=0)) if attack.any() else float("nan"),
    }


def category_recall(y_cat: np.ndarray, y_pred: np.ndarray, category_id: int, label_mode: str) -> float:
    mask = y_cat == category_id
    if not mask.any():
        return float("nan")
    if label_mode == "multiclass":
        return float((y_pred[mask] == category_id).mean())
    return float((y_pred[mask] == 1).mean())


def confusion(y_true: np.ndarray, y_pred: np.ndarray, num_classes: int) -> np.ndarray:
    return confusion_matrix(y_true, y_pred, labels=np.arange(num_classes))


def forgetting_metrics(R: np.ndarray) -> dict:
    """R[i, j]: performance on task j after training task i (NaN where undefined)."""
    T = R.shape[0]
    if T < 2:
        return {"bwt": float("nan"), "avg_forgetting": float("nan"), "final_avg": float(np.nanmean(R[-1]))}
    bwt = np.nanmean([R[T - 1, j] - R[j, j] for j in range(T - 1)])
    forg = np.nanmean([np.nanmax(R[j:T - 1, j]) - R[T - 1, j] for j in range(T - 1)])
    return {"bwt": float(bwt), "avg_forgetting": float(forg), "final_avg": float(np.nanmean(R[T - 1]))}
