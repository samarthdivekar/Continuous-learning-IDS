"""The live model: scores sensor traffic and learns from analyst labels without forgetting.

It is a separate copy of the headline model (GNN + EWC + replay), restored from the final task-sequence
checkpoint with its EWC state, and with its replay buffer refilled from the training windows of every
attack category. Learning from live labels therefore runs exactly like one more task of the continual
sequence: new windows, EWC penalty, replayed old-attack windows. The checkpoint-loaded models that answer
/predict are never touched; /live/reset rebuilds this copy from the checkpoint.

Every adaptation is a candidate. Before and after it, the model is scored on held-out test windows of the
training data (two per task); if old-attack macro-F1 drops by more than `max_drop`, the update is rolled
back and the response says why. That is what "learns your network without forgetting old attacks" means
here, measured each time rather than asserted.
"""
from __future__ import annotations

import time

import numpy as np
import torch
from sklearn.metrics import f1_score

from src.graph.window_builder import build_window_graph
from src.ingestion.columns import canonical_name
from src.training.learners import load_learner_checkpoint, make_learner
from src.utils.config import class_names, num_classes
from src.utils.logging import get_logger

log = get_logger(__name__)

LIVE_MODEL = "gnn_ewc_replay"
LIVE_WINDOW_OFFSET = 10_000_000        # live graphs get window ids far from the dataset's


class LiveEngine:
    def __init__(self, svc, model: str = LIVE_MODEL, max_drop: float = 0.02, eval_windows_per_task: int = 2):
        self.svc = svc
        self.model_name = model
        self.max_drop = max_drop
        self.eval_windows_per_task = eval_windows_per_task
        self.learner = None
        self.version = 0                     # bumped on every accepted adaptation and on reset
        self.threshold: float | None = None  # novelty (energy) above this = unfamiliar
        self.history: list[dict] = []
        self._eval_set = None

    # ------------------------------------------------------------------ setup
    @property
    def names(self) -> list[str]:
        return class_names(self.svc.cfg)

    def ensure(self):
        if self.learner is None:
            self._build()
        return self.learner

    def _build(self) -> None:
        svc = self.svc
        if not svc.data_available:
            raise FileNotFoundError("processed data missing (run experiments.prepare_data)")
        data, cfg = svc.data, svc.cfg
        node_in = 3 if cfg["graph"]["node_features"] == "degree" else 1
        learner = make_learner(self.model_name, cfg, data.meta["n_features"], num_classes(cfg), svc.device,
                               node_in=node_in)
        load_learner_checkpoint(learner, svc.checkpoint_dir() / f"{self.model_name}_after_task{data.n_tasks - 1}.pt")
        if getattr(learner, "buffer", None) is not None:
            for t in range(data.n_tasks):
                learner.buffer.add_many(data.graphs(t, "train"))
        self.learner = learner
        self.threshold = self._calibrate_threshold()
        log.info("live model ready: %s, novelty threshold %.3f", self.model_name, self.threshold)

    def _calibrate_threshold(self, target_fpr: float = 0.05, max_windows: int = 24) -> float:
        """Energy score that 95 % of held-out validation flows (benign and known attacks) stay below."""
        data = self.svc.data
        graphs = [g for t in range(data.n_tasks) for g in data.graphs(t, "val")]
        rng = np.random.default_rng(0)
        pick = rng.permutation(len(graphs))[:max_windows]
        scores = np.concatenate([self._energy(self.learner.predict_details(graphs[i])[0]) for i in pick])
        return float(np.quantile(scores, 1 - target_fpr))

    @staticmethod
    def _energy(logits: np.ndarray) -> np.ndarray:
        m = logits.max(axis=1, keepdims=True)
        return -(m[:, 0] + np.log(np.exp(logits - m).sum(axis=1)))

    # ---------------------------------------------------------------- scoring
    def graph(self, flows: list[dict], labels: list[int | None] | None = None, window_id: int = -1):
        g = self.svc.flows_to_graph(flows)            # rejects incomplete flows (MissingFeaturesError)
        if labels is not None:
            y = np.array([-1 if lab is None else int(lab) for lab in labels], dtype=np.int64)
            g.label_mask = torch.from_numpy(y >= 0)
            g.y = torch.from_numpy(np.where(y >= 0, y, 0))
        g.window_id = int(window_id)
        return g

    def score(self, flows: list[dict]) -> dict:
        with self.svc.lock:
            learner = self.ensure()
            g = self.graph(flows)
            logits, _ = learner.predict_details(g)
        probs = torch.softmax(torch.from_numpy(logits), dim=-1).numpy()
        pred = probs.argmax(1)
        energy = self._energy(logits)
        unfamiliar = energy > self.threshold
        names = self.names
        return {"model": self.model_name, "version": self.version, "n_flows": int(len(pred)),
                "n_nodes": int(g.num_nodes), "labels": [names[i] for i in pred],
                "confidence": [round(float(c), 4) for c in probs.max(1)],
                "probs": probs.round(5).tolist(), "novelty": [round(float(e), 4) for e in energy],
                "unfamiliar": [bool(u) for u in unfamiliar], "threshold": self.threshold,
                "counts": {names[i]: int((pred == i).sum()) for i in np.unique(pred)}}

    # --------------------------------------------------------------- learning
    def _held_out(self):
        """Two test windows per task of the training data: the 'did it forget?' check."""
        if self._eval_set is None:
            data = self.svc.data
            rng = np.random.default_rng(0)
            gs = []
            for t in range(data.n_tasks):
                test = data.graphs(t, "test")
                gs += [test[i] for i in rng.permutation(len(test))[: self.eval_windows_per_task]]
            self._eval_set = gs
        return self._eval_set

    def _old_attack_metrics(self) -> dict:
        y_true, y_pred = [], []
        for g in self._held_out():
            y_true.append(g.y.numpy())
            y_pred.append(self.learner.predict_proba(g).argmax(1))
        yt, yp = np.concatenate(y_true), np.concatenate(y_pred)
        labels = sorted(set(yt.tolist()))
        benign = yt == 0
        return {"macro_f1": float(f1_score(yt, yp, labels=labels, average="macro", zero_division=0)),
                "fpr": float((yp[benign] != 0).mean()) if benign.any() else 0.0,
                "attack_recall": float((yp[~benign] == yt[~benign]).mean()) if (~benign).any() else 1.0,
                "n_flows": int(len(yt))}

    def adapt(self, windows: list[tuple[list[dict], list[int | None]]], epochs: int | None = None) -> dict:
        """Learn from labelled live windows: [(flows, label id per flow or None)]. Gated (see module doc)."""
        t0 = time.time()
        with self.svc.lock:
            learner = self.ensure()
            graphs = [self.graph(f, labs, window_id=LIVE_WINDOW_OFFSET + 100_000 * self.version + i)
                      for i, (f, labs) in enumerate(windows) if any(lab is not None for lab in labs)]
            if not graphs:
                return {"accepted": False, "reason": "no labelled flows", "version": self.version}
            n_labelled = int(sum(int(g.label_mask.sum()) for g in graphs))
            before = self._old_attack_metrics()
            snap = learner.snapshot_state()
            learner.learn(graphs, tag=f"live_v{self.version + 1}", epochs=epochs)
            after = self._old_attack_metrics()
            drop = before["macro_f1"] - after["macro_f1"]
            accepted = drop <= self.max_drop
            if accepted:
                self.version += 1
            else:
                learner.restore_state(snap)
        rec = {"accepted": accepted, "version": self.version, "windows": len(graphs), "labelled_flows": n_labelled,
               "seconds": round(time.time() - t0, 1), "old_attacks_before": before, "old_attacks_after": after,
               "reason": None if accepted else
               f"rolled back: macro-F1 on old attacks fell by {drop:.3f} (limit {self.max_drop:.3f})"}
        self.history.append(rec)
        return rec

    def reset(self) -> dict:
        with self.svc.lock:
            self.learner = None
            self._build()
            self.version += 1
        self.history.append({"reset": True, "version": self.version})
        return {"reset": True, "version": self.version}

    def describe(self) -> dict:
        return {"model": self.model_name, "loaded": self.learner is not None, "version": self.version,
                "novelty_threshold": self.threshold, "max_drop": self.max_drop,
                "classes": self.names, "history": self.history[-10:]}


def label_id(names: list[str], label: str | None) -> int | None:
    if label is None:
        return None
    lookup = {canonical_name(n): i for i, n in enumerate(names)}
    key = canonical_name(label)
    if key not in lookup:
        raise ValueError(f"unknown label {label!r}; use one of {names}")
    return lookup[key]
