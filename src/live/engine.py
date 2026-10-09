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

Every accepted adaptation is saved to `<cache>/live/<dataset>/<label_mode>/live_state.pt` (weights,
optimiser, EWC state and the labelled live windows, as plain tensors so it loads in PyTorch's safe mode),
and restored when the service starts, so what the model learned survives a restart. /live/reset deletes it.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import f1_score
from torch_geometric.data import Data

from src.ingestion.columns import canonical_name
from src.training.learners import load_learner_checkpoint, make_learner
from src.utils.config import REPO_ROOT, class_names, num_classes
from src.utils.logging import get_logger
from src.utils.safe_load import load_checkpoint

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
        self.live_graphs: list[Data] = []    # every labelled live window an accepted update learned from
        self.restored_from: str | None = None
        self._eval_set = None

    # ------------------------------------------------------------------ setup
    @property
    def names(self) -> list[str]:
        return class_names(self.svc.cfg)

    @property
    def state_path(self) -> Path:
        cfg = self.svc.cfg
        base = Path(cfg["paths"]["cache"])
        base = base if base.is_absolute() else REPO_ROOT / base
        return base / "live" / cfg["dataset"] / cfg["label_mode"] / "live_state.pt"

    def ensure(self):
        if self.learner is None:
            self._build()
        return self.learner

    def _fresh_learner(self):
        """The final task-sequence checkpoint, replay buffer refilled from every task's training windows."""
        svc = self.svc
        data, cfg = svc.data, svc.cfg
        node_in = 3 if cfg["graph"]["node_features"] == "degree" else 1
        learner = make_learner(self.model_name, cfg, data.meta["n_features"], num_classes(cfg), svc.device,
                               node_in=node_in)
        load_learner_checkpoint(learner, svc.checkpoint_dir() / f"{self.model_name}_after_task{data.n_tasks - 1}.pt")
        if getattr(learner, "buffer", None) is not None:
            for t in range(data.n_tasks):
                learner.buffer.add_many(data.graphs(t, "train"))
        return learner

    def _build(self, restore: bool = True) -> None:
        if not self.svc.data_available:
            raise FileNotFoundError("processed data missing (run experiments.prepare_data)")
        self.learner = self._fresh_learner()
        self.live_graphs = []
        if restore:
            self._restore_saved()
        self.threshold = self._calibrate_threshold()
        log.info("live model ready: %s v%d, novelty threshold %.3f", self.model_name, self.version, self.threshold)

    # ------------------------------------------------------------ persistence
    @staticmethod
    def _plain(obj):
        """JSON-safe copy (numpy scalars -> floats) so the state file loads with weights_only=True."""
        return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))

    @staticmethod
    def _graph_to_dict(g: Data) -> dict:
        d = {k: g[k].detach().cpu() for k in ("x", "edge_index", "edge_attr", "y") if k in g}
        if "label_mask" in g:
            d["label_mask"] = g.label_mask.detach().cpu()
        d["window_id"] = int(g.window_id)
        return d

    @staticmethod
    def _dict_to_graph(d: dict) -> Data:
        g = Data(x=d["x"], edge_index=d["edge_index"], edge_attr=d["edge_attr"], y=d["y"])
        if "label_mask" in d:
            g.label_mask = d["label_mask"]
        g.window_id = int(d["window_id"])
        return g

    def _save(self) -> None:
        learner = self.learner
        state = {"format": 1, "model_name": self.model_name, "version": self.version,
                 "model": {k: v.detach().cpu() for k, v in learner.model.state_dict().items()},
                 "optimizer": learner.optimizer.state_dict(),
                 "ewc": None, "live_graphs": [self._graph_to_dict(g) for g in self.live_graphs],
                 "history": self._plain(self.history[-50:])}
        if getattr(learner, "ewc", None) is not None:
            ewc = learner.ewc.state_dict()
            ewc["history"] = self._plain(ewc.get("history", []))
            state["ewc"] = ewc
        path = self.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        torch.save(state, tmp)
        tmp.replace(path)                    # atomic: a crash mid-save never leaves a half-written state

    def _restore_saved(self) -> None:
        path = self.state_path
        if not path.exists():
            return
        try:
            st = load_checkpoint(path, map_location=self.svc.device)
            if st.get("model_name") != self.model_name:
                raise ValueError(f"state is for {st.get('model_name')}")
            learner = self.learner
            learner.model.load_state_dict(st["model"])
            learner.optimizer.load_state_dict(st["optimizer"])
            if st.get("ewc") is not None and getattr(learner, "ewc", None) is not None:
                learner.ewc.load_state_dict(st["ewc"], self.svc.device)
            self.live_graphs = [self._dict_to_graph(d) for d in st.get("live_graphs", [])]
            if getattr(learner, "buffer", None) is not None:
                learner.buffer.add_many(self.live_graphs)
            self.version = max(self.version, int(st["version"]))
            self.history = list(st.get("history", []))
            self.restored_from = str(path)
            log.info("live model restored from %s (v%d, %d learned windows)", path, self.version,
                     len(self.live_graphs))
        except Exception as exc:                     # a bad state file must not take the service down
            log.warning("could not restore live state %s (%s); starting from the trained model", path, exc)
            self.restored_from = None
            self.learner, self.live_graphs = self._fresh_learner(), []   # undo a partial restore

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

    def score(self, flows: list[dict], context: list[dict] | None = None) -> dict:
        """Score `flows`. `context` = the site's recent earlier flows: they join the graph (so a short
        capture chunk is judged inside a window of comparable size to training) but only `flows` are
        returned."""
        context = context or []
        with self.svc.lock:
            learner = self.ensure()
            g = self.graph(context + flows)
            logits, _ = learner.predict_details(g)
            logits = logits[len(context):]
        probs = torch.softmax(torch.from_numpy(logits), dim=-1).numpy()
        pred = probs.argmax(1)
        energy = self._energy(logits)
        unfamiliar = energy > self.threshold
        names = self.names
        return {"model": self.model_name, "version": self.version, "n_flows": int(len(pred)),
                "n_nodes": int(g.num_nodes), "n_context": len(context), "labels": [names[i] for i in pred],
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
                self.live_graphs.extend(graphs)
            else:
                learner.restore_state(snap)
        rec = {"accepted": accepted, "version": self.version, "windows": len(graphs), "labelled_flows": n_labelled,
               "seconds": round(time.time() - t0, 1), "old_attacks_before": before, "old_attacks_after": after,
               "reason": None if accepted else
               f"rolled back: macro-F1 on old attacks fell by {drop:.3f} (limit {self.max_drop:.3f})"}
        self.history.append(rec)
        if accepted:
            with self.svc.lock:
                self._save()
            rec["saved"] = True
        return rec

    def fpr_study(self, flows: list[dict], teach_fraction: float = 0.5, epochs: int | None = None) -> dict:
        """Measure what teaching does to false alarms on the user's own benign traffic, honestly:
        split the flows into a teach half and a held-out half, measure the false-positive rate on the
        held-out half before and after teaching the teach half as benign, and restore the model so this
        is a measurement, not a silent change. Also report old-attack macro-F1 before/after, since
        teaching on benign-only traffic could trade attack recall for fewer false alarms."""
        with self.svc.lock:
            learner = self.ensure()
            k = int(len(flows) * teach_fraction)
            teach, hold = flows[:k], flows[k:]
            if len(teach) < 1 or len(hold) < 1:
                raise ValueError("need enough flows for both a teach split and a held-out split")

            def fpr(fl):
                logits, _ = learner.predict_details(self.graph(fl))
                pred = logits.argmax(1)
                return float((pred != 0).mean()), int((pred != 0).sum())

            fpr_before, flagged_before = fpr(hold)
            old_before = self._old_attack_metrics()
            snap = learner.snapshot_state()
            g = self.graph(teach, labels=[0] * len(teach), window_id=LIVE_WINDOW_OFFSET)
            learner.learn([g], tag="fpr_study", epochs=epochs)
            fpr_after, flagged_after = fpr(hold)
            old_after = self._old_attack_metrics()
            learner.restore_state(snap)        # measurement only: the deployed model is left unchanged
        return {"n_flows": len(flows), "n_teach": len(teach), "n_holdout": len(hold),
                "fpr_before": fpr_before, "fpr_after": fpr_after,
                "flagged_before": flagged_before, "flagged_after": flagged_after,
                "old_attack_f1_before": old_before["macro_f1"], "old_attack_f1_after": old_after["macro_f1"],
                "old_attack_recall_before": old_before["attack_recall"],
                "old_attack_recall_after": old_after["attack_recall"], "model_unchanged": True}

    def reset(self) -> dict:
        """Back to the trained model: the saved live state is deleted, not just ignored."""
        with self.svc.lock:
            self.state_path.unlink(missing_ok=True)
            self.restored_from = None
            self.learner = None
            self._build(restore=False)
            self.version += 1
        self.history.append({"reset": True, "version": self.version})
        return {"reset": True, "version": self.version}

    def describe(self) -> dict:
        if self.learner is None and self.state_path.exists():
            with self.svc.lock:              # a saved state exists: load it so the version shown is real
                self.ensure()
        return {"model": self.model_name, "loaded": self.learner is not None, "version": self.version,
                "novelty_threshold": self.threshold, "max_drop": self.max_drop,
                "classes": self.names, "history": self.history[-10:],
                "learned_windows": len(self.live_graphs), "saved": self.state_path.exists(),
                "restored_from_disk": self.restored_from is not None}


def label_id(names: list[str], label: str | None) -> int | None:
    if label is None:
        return None
    lookup = {canonical_name(n): i for i, n in enumerate(names)}
    key = canonical_name(label)
    if key not in lookup:
        raise ValueError(f"unknown label {label!r}; use one of {names}")
    return lookup[key]
