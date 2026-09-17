"""Static tabular baseline: XGBoost trained once on task 1, then frozen.

No EWC: EWC needs parameter gradients, and a tree ensemble has none.
The model can only ever output the classes present in task 1; in multiclass
mode later attack categories are, by construction, unpredictable for it
("blind to new"). In binary mode it may still flag novel attacks that look
anomalous relative to task-1 benign traffic, which is the fair comparison.
"""
from __future__ import annotations

import numpy as np
import xgboost as xgb


class StaticXGBoost:
    name = "xgboost_static"

    def __init__(self, num_classes: int, params: dict, seed: int = 0, device: str = "cpu"):
        self.num_classes = num_classes
        self.params = dict(params)
        self.seed = seed
        self.device = device
        self.model: xgb.XGBClassifier | None = None
        self.classes_: np.ndarray | None = None
        self.trained = False

    def fit(self, X: np.ndarray, y: np.ndarray, sample_weight: np.ndarray | None = None) -> None:
        if self.trained:
            return  # frozen after the first task by design
        self.classes_ = np.unique(y)  # XGBoost needs contiguous labels 0..k-1
        remap = {c: i for i, c in enumerate(self.classes_)}
        y_local = np.vectorize(remap.get)(y)
        objective = "binary:logistic" if len(self.classes_) == 2 else "multi:softprob"
        self.model = xgb.XGBClassifier(objective=objective, random_state=self.seed,
                                       device=self.device, n_jobs=-1, **self.params)
        self.model.fit(X, y_local, sample_weight=sample_weight)
        self.trained = True

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Probabilities over the GLOBAL class space (unseen classes get 0)."""
        local = self.model.predict_proba(X)
        out = np.zeros((len(X), self.num_classes), dtype=np.float32)
        out[:, self.classes_] = local
        return out

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.predict_proba(X).argmax(axis=1)
