"""Calibration of predicted probabilities: does a 0.9 confidence mean 90 % correct?

Top-label calibration. For every flow, confidence = the largest class probability and
correct = (argmax == true class). Flows are grouped into equal-width confidence bins:

  reliability  per bin: number of flows, mean confidence, accuracy
  ECE          expected calibration error = Σ_b (n_b / N) · |accuracy_b − confidence_b|
  MCE          maximum calibration error = max_b |accuracy_b − confidence_b| over non-empty bins
  Brier        multiclass Brier score = mean over flows of Σ_c (p_c − 1[c = y])²

On intrusion data most flows are benign, so an overall ECE mostly describes benign
traffic. The experiment therefore also reports ECE on the attack flows and on the benign
flows separately.
"""
from __future__ import annotations

import numpy as np


def reliability(probs: np.ndarray, y: np.ndarray, n_bins: int = 15) -> list[dict]:
    conf = probs.max(1)
    correct = probs.argmax(1) == y
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    # bin b holds confidences in (edges[b], edges[b+1]]; a confidence of exactly 0 goes to bin 0
    idx = np.clip(np.searchsorted(edges, conf, side="left") - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        n = int(m.sum())
        rows.append({"bin": b, "lower": float(edges[b]), "upper": float(edges[b + 1]), "n": n,
                     "confidence": float(conf[m].mean()) if n else float("nan"),
                     "accuracy": float(correct[m].mean()) if n else float("nan")})
    return rows


def calibration_errors(probs: np.ndarray, y: np.ndarray, n_bins: int = 15) -> dict:
    if len(y) == 0:
        return {"n": 0, "ece": float("nan"), "mce": float("nan"), "brier": float("nan"),
                "mean_confidence": float("nan"), "accuracy": float("nan")}
    rows = [r for r in reliability(probs, y, n_bins) if r["n"]]
    gaps = np.array([abs(r["accuracy"] - r["confidence"]) for r in rows])
    weights = np.array([r["n"] for r in rows]) / len(y)
    onehot = np.zeros_like(probs)
    onehot[np.arange(len(y)), y] = 1.0
    return {"n": len(y), "ece": float((weights * gaps).sum()), "mce": float(gaps.max()),
            "brier": float(((probs - onehot) ** 2).sum(1).mean()),
            "mean_confidence": float(probs.max(1).mean()), "accuracy": float((probs.argmax(1) == y).mean())}
