"""Calibrated abstention with class-conditional (Mondrian) split conformal prediction.

For every class c, nonconformity scores s = 1 − p(c | x) are collected on
VALIDATION flows whose true class is c, and q_c is their
⌈(n_c + 1)(1 − α)⌉ / n_c quantile. A test flow's prediction set is
{c : 1 − p(c | x) ≤ q_c}. Guarantee (exchangeability): for each class,
P(true class ∈ set) ≥ 1 − α — per class, so rare attacks keep their coverage
instead of being averaged away by benign traffic.

Decision rule used by the product:
  |set| == 1  → act on that label
  otherwise   → ABSTAIN ("uncertain — send to an analyst")
"""
from __future__ import annotations

import numpy as np


def fit_class_thresholds(probs: np.ndarray, y: np.ndarray, alpha: float, min_n: int = 20) -> dict[int, float]:
    q = {}
    for c in np.unique(y):
        s = 1.0 - probs[y == c, c]
        n = len(s)
        if n < min_n:          # too few calibration flows for a meaningful per-class quantile
            continue
        level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n)
        q[int(c)] = float(np.quantile(s, level, method="higher"))
    return q


def prediction_sets(probs: np.ndarray, q: dict[int, float], fallback: float) -> np.ndarray:
    """Boolean (n, K) membership. Classes without their own threshold use `fallback`."""
    K = probs.shape[1]
    thr = np.array([q.get(c, fallback) for c in range(K)])
    return (1.0 - probs) <= thr[None, :]


def evaluate(probs: np.ndarray, y: np.ndarray, sets: np.ndarray, benign: int = 0) -> dict:
    size = sets.sum(axis=1)
    covered = sets[np.arange(len(y)), y]
    single = size == 1
    pred = probs.argmax(1)
    acted = single                                  # flows the system acts on automatically
    ben = y == benign
    wrong_alarm = ben & (pred != benign)            # argmax would have raised a false alarm
    return {
        "coverage": float(covered.mean()),
        "abstain_rate": float((~single).mean()),
        "accuracy_acted": float((pred[acted] == y[acted]).mean()) if acted.any() else float("nan"),
        "fpr_argmax": float(wrong_alarm[ben].mean()) if ben.any() else float("nan"),
        "fpr_acted": float((wrong_alarm & acted)[ben].sum() / max(1, (ben & acted).sum())),
        "false_alarms_argmax": int(wrong_alarm.sum()),
        "false_alarms_after_abstention": int((wrong_alarm & acted).sum()),
        "attack_abstain_rate": float((~single)[~ben].mean()) if (~ben).any() else float("nan"),
        "mean_set_size": float(size.mean()),
    }
