"""Feature scaling: signed log1p -> StandardScaler (fit on task 1 train only) -> clip.

CICFlowMeter features are extremely heavy-tailed (byte rates span ~10 orders
of magnitude). A StandardScaler fitted on task 1 alone would give z-scores in
the thousands for later volumetric attacks (DoS/DDoS), destabilising neural
training. sign(x)*log1p(|x|) compresses the range first; clipping bounds the
residual outliers. The scaler is fitted on task-1 *training* flows only and
reused unchanged for every later task, so no information from future tasks
leaks into preprocessing.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np


class FeatureScaler:
    def __init__(self, clip_value: float = 10.0):
        self.clip_value = float(clip_value)
        self.mean_: np.ndarray | None = None
        self.scale_: np.ndarray | None = None
        self.columns: list[str] | None = None

    @staticmethod
    def _log(x: np.ndarray) -> np.ndarray:
        return np.sign(x) * np.log1p(np.abs(x))

    def fit(self, X: np.ndarray, columns: list[str]) -> "FeatureScaler":
        Z = self._log(X.astype(np.float64))
        self.mean_ = Z.mean(axis=0)
        std = Z.std(axis=0)
        std[std < 1e-8] = 1.0  # constant-in-task-1 features pass through centred
        self.scale_ = std
        self.columns = list(columns)
        return self

    def transform(self, X: np.ndarray, chunk: int = 500_000) -> np.ndarray:
        if self.mean_ is None:
            raise RuntimeError("FeatureScaler not fitted")
        out = np.empty(X.shape, dtype=np.float32)
        for s in range(0, len(X), chunk):   # chunked: bounded float64 temporaries on large datasets
            Z = (self._log(X[s:s + chunk].astype(np.float64)) - self.mean_) / self.scale_
            out[s:s + chunk] = np.clip(Z, -self.clip_value, self.clip_value)
        return out

    def inverse_transform(self, Z: np.ndarray) -> np.ndarray:
        """Approximate original units (exact unless the value was clipped). Used to
        show analysts real feature values, e.g. 'SYN Flag Count = 1'."""
        L = np.asarray(Z, dtype=np.float64) * self.scale_ + self.mean_
        return np.sign(L) * np.expm1(np.abs(L))

    def save(self, path: Path) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"clip_value": self.clip_value, "mean": self.mean_.tolist(),
                       "scale": self.scale_.tolist(), "columns": self.columns}, fh)

    @classmethod
    def load(cls, path: Path) -> "FeatureScaler":
        with open(path, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        s = cls(d["clip_value"])
        s.mean_, s.scale_, s.columns = np.array(d["mean"]), np.array(d["scale"]), d["columns"]
        return s
