"""ML service layer: model loading, prediction, graph summaries and the live demo.

Used in-process by the API (local runs) or behind its own container
(src/api/ml_app.py) when ML_SERVICE_URL is set for the public API.
"""
from __future__ import annotations

import os
import pickle
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.db.models import DriftEventRow, Metric, WindowStat
from src.evaluation.stream import StreamRunner
from src.graph.window_builder import build_window_graph
from src.ingestion.columns import canonical_name
from src.preprocessing.pipeline import load_processed, processed_dir
from src.preprocessing.scaling import FeatureScaler
from src.training.learners import make_learner
from src.utils.config import class_names, load_config, num_classes, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed

log = get_logger(__name__)

PREDICT_MODELS = ["gnn_ewc_replay", "gnn_naive", "ffnn_ewc_replay", "xgboost_static"]
DEMO_RUNS = [("gnn_ewc_replay", "adwin"), ("gnn_naive", "adwin"), ("ffnn_ewc_replay", "adwin"),
             ("xgboost_static", "never")]


def _utc(ts) -> datetime:
    try:
        t = pd.Timestamp(ts)
        return (t.tz_localize("UTC") if t.tzinfo is None else t).to_pydatetime()
    except Exception:
        return datetime.now(timezone.utc)


def service_config() -> dict:
    dataset = os.environ.get("DATASET", "cicids2017")
    mode = os.environ.get("LABEL_MODE", "multiclass")
    overrides = [f"label_mode={mode}"]
    if os.environ.get("DEVICE"):
        overrides.append(f"train.device={os.environ['DEVICE']}")
    from src.utils.selection import apply_selection
    return apply_selection(load_config(dataset, overrides))


class MLService:
    def __init__(self, cfg: dict | None = None, session_factory=None):
        self.cfg = cfg or service_config()
        self.Session = session_factory
        self.device = get_device(self.cfg["train"]["device"])
        self._data = None
        self._scaler = None
        self._window_index: dict[int, tuple[int, str, int]] | None = None
        self.models: dict = {}
        self.model_errors: dict[str, str] = {}
        self.demo: DemoRunner | None = None
        self.lock = threading.RLock()

    # ------------------------------------------------------------------ data
    @property
    def data_available(self) -> bool:
        return (processed_dir(self.cfg) / "meta.json").exists()

    @property
    def data(self):
        if self._data is None:
            self._data = load_processed(self.cfg)
        return self._data

    @property
    def scaler(self) -> FeatureScaler:
        if self._scaler is None:
            self._scaler = FeatureScaler.load(processed_dir(self.cfg) / "scaler.json")
        return self._scaler

    def window_index(self) -> dict[int, tuple[int, str, int]]:
        if self._window_index is None:
            idx = {}
            for t in range(self.data.n_tasks):
                for split in ("train", "val", "test"):
                    for i, g in enumerate(self.data.graphs(t, split)):
                        idx[int(g.window_id)] = (t, split, i)
            self._window_index = idx
        return self._window_index

    def get_window(self, window_id: int):
        loc = self.window_index().get(int(window_id))
        if loc is None:
            return None
        t, split, i = loc
        return self.data.graphs(t, split)[i]

    # ---------------------------------------------------------------- models
    def checkpoint_dir(self) -> Path:
        return resolve_path(self.cfg, "checkpoints") / self.cfg["dataset"] / self.cfg["label_mode"]

    def load_models(self) -> None:
        if not self.data_available:
            self.model_errors["*"] = "processed data missing (run experiments.prepare_data)"
            return
        n_tasks, K = self.data.n_tasks, num_classes(self.cfg)
        node_in = 3 if self.cfg["graph"]["node_features"] == "degree" else 1
        for name in PREDICT_MODELS:
            try:
                learner = make_learner(name, self.cfg, self.data.meta["n_features"], K, self.device, node_in=node_in)
                if learner.family == "xgb":
                    with open(self.checkpoint_dir() / f"{name}_after_task0.pkl", "rb") as fh:
                        learner.model = pickle.load(fh)
                else:
                    state = torch.load(self.checkpoint_dir() / f"{name}_after_task{n_tasks - 1}.pt",
                                       map_location=self.device, weights_only=False)
                    learner.model.load_state_dict(state["model"])
                self.models[name] = learner
            except FileNotFoundError as exc:
                self.model_errors[name] = f"checkpoint missing: {exc.filename}"
        log.info("loaded models: %s; missing: %s", list(self.models), self.model_errors)

    def warm_start(self, learner, task: int = 0) -> bool:
        """Restore `learner` to its state right after training task `task` from the
        checkpoints written by experiments/run_continual.py. Model weights and EWC
        state come from the checkpoint; replay buffers are refilled from that
        task's training windows exactly as learn() does after training."""
        d = self.checkpoint_dir()
        try:
            if learner.family == "xgb":
                with open(d / f"{learner.name}_after_task{task}.pkl", "rb") as fh:
                    learner.model = pickle.load(fh)
                return True
            state = torch.load(d / f"{learner.name}_after_task{task}.pt", map_location=self.device,
                               weights_only=False)
        except FileNotFoundError:
            return False
        learner.model.load_state_dict(state["model"])
        if getattr(learner, "ewc", None) is not None and "ewc" in state:
            learner.ewc.load_state_dict(state["ewc"], self.device)
        graphs = self.data.graphs(task, "train")
        buf = getattr(learner, "buffer", None)
        if buf is not None:
            if learner.family == "gnn":
                buf.add_many(graphs)
            else:
                buf.add(torch.cat([g.edge_attr for g in graphs]).numpy(), torch.cat([g.y for g in graphs]).numpy())
                learner.buffered_windows.update(int(g.window_id) for g in graphs)
        learner.n_learn_calls += 1
        return True

    def active_learners(self) -> dict:
        """Live demo learners take precedence once they are READY (warm-started or
        trained on task 1); until then, and after a failed demo, /predict keeps
        using the checkpoint-loaded models instead of half-initialised ones."""
        if self.demo is not None and self.demo.ready:
            return {r.learner.name: r.learner for r in self.demo.runners}
        return self.models

    # ------------------------------------------------------------ prediction
    def flows_to_graph(self, flows: list[dict]):
        cols = self.scaler.columns
        X = np.zeros((len(flows), len(cols)), dtype=np.float64)
        missing: set[str] = set()
        for i, f in enumerate(flows):
            feats = {canonical_name(k): v for k, v in (f.get("features") or {}).items()}
            for j, c in enumerate(cols):
                v = feats.get(c)
                if v is None:
                    missing.add(c)
                    continue
                X[i, j] = float(v) if np.isfinite(float(v)) else 0.0
        Xs = self.scaler.transform(X)
        g = build_window_graph(np.array([f["src_ip"] for f in flows]), np.array([f["dst_ip"] for f in flows]),
                               Xs, np.zeros(len(flows), dtype=np.int64), self.cfg["graph"]["node_features"],
                               window_id=-1)
        return g, sorted(missing)

    def predict(self, flows: list[dict] | None = None, window_id: int | None = None,
                models: list[str] | None = None, max_flows_returned: int = 500) -> dict:
        warnings = []
        if window_id is not None:
            g = self.get_window(window_id)
            if g is None:
                raise KeyError(f"window {window_id} not found")
        else:
            g, missing = self.flows_to_graph(flows or [])
            if missing:
                warnings.append(f"{len(missing)} feature(s) absent and imputed as 0, e.g. {missing[:5]}")
        names = class_names(self.cfg)
        out = {"n_flows": int(g.edge_index.shape[1]), "n_nodes": int(g.num_nodes), "models": {},
               "warnings": warnings, "unavailable": {}}
        with self.lock:
            learners = self.active_learners()
            for name in (models or list(learners)):
                if name not in learners:
                    out["unavailable"][name] = self.model_errors.get(name, "not loaded")
                    continue
                p = learners[name].predict_proba(g)
                pred = p.argmax(1)
                out["models"][name] = {
                    "labels": [names[i] for i in pred[:max_flows_returned]],
                    "confidence": [round(float(c), 4) for c in p.max(1)[:max_flows_returned]],
                    "counts": {names[i]: int((pred == i).sum()) for i in np.unique(pred)},
                }
        if window_id is not None:
            out["true_counts"] = {names[i]: int(c) for i, c in
                                  enumerate(np.bincount((g.y > 0).long().numpy() if self.cfg["label_mode"] == "binary"
                                                        else g.y.numpy(), minlength=len(names))) if c}
        return out

    # --------------------------------------------------------------- graphs
    def graph_summary(self, window_id: int, max_nodes: int = 150, model: str | None = None) -> dict:
        """Node/edge summary of a window. With `model`, every flow is also
        classified by that model and edges carry how many of their flows it got
        wrong (the Graph Explorer's prediction overlay)."""
        g = self.get_window(window_id)
        if g is None:
            raise KeyError(f"window {window_id} not found")
        cats = self.cfg["categories"]
        src, dst = g.edge_index.numpy()
        y = g.y.numpy()
        n = g.num_nodes
        deg = np.bincount(src, minlength=n) + np.bincount(dst, minlength=n)
        out_deg = np.bincount(src, minlength=n)
        in_deg = np.bincount(dst, minlength=n)
        attack_deg = np.bincount(src[y > 0], minlength=n) + np.bincount(dst[y > 0], minlength=n)

        wrong = np.zeros(len(y), bool)
        pred_cat = y.copy()
        model_info = None
        if model:
            with self.lock:
                learners = self.active_learners()
                if model not in learners:
                    raise KeyError(f"model {model} not loaded")
                p = learners[model].predict_proba(g)
            pred = p.argmax(1)
            truth = (y > 0).astype(int) if self.cfg["label_mode"] == "binary" else y
            wrong = pred != truth
            pred_cat = pred if self.cfg["label_mode"] == "multiclass" else np.where(pred > 0, y.clip(min=1), 0)
            model_info = {"name": model, "n_wrong": int(wrong.sum()), "accuracy": float(1 - wrong.mean()),
                          "false_alarms": int((wrong & (y == 0)).sum()), "missed_attacks": int((wrong & (y > 0)).sum())}

        # keep the busiest hosts, always including hosts involved in attacks
        order = np.lexsort((-deg, -(attack_deg > 0).astype(np.int64)))
        keep = order[:max_nodes]
        keep_set = np.zeros(n, bool)
        keep_set[keep] = True
        mask = keep_set[src] & keep_set[dst]
        pairs = pd.DataFrame({"s": src[mask], "t": dst[mask], "attack": y[mask] > 0, "cat": y[mask],
                              "wrong": wrong[mask], "pcat": pred_cat[mask]})
        agg = pairs.groupby(["s", "t"]).agg(flows=("attack", "size"), attack_flows=("attack", "sum"),
                                            top_cat=("cat", "max"), wrong=("wrong", "sum"),
                                            pred_cat=("pcat", "max")).reset_index()
        return {
            "window_id": int(window_id), "task_id": int(g.task_id), "split": int(g.split),
            "window_start": g.window_start, "window_end": g.window_end,
            "task_category": self.data.task_categories[int(g.task_id)],
            "n_nodes": int(n), "n_edges": int(len(y)), "n_attack_edges": int((y > 0).sum()),
            "category_counts": {cats[i]: int(c) for i, c in enumerate(np.bincount(y, minlength=len(cats))) if c},
            "nodes": [{"id": int(i), "degree": int(deg[i]), "out_degree": int(out_deg[i]), "in_degree": int(in_deg[i]),
                       "attack_degree": int(attack_deg[i])} for i in keep],
            "edges": [{"source": int(r.s), "target": int(r.t), "flows": int(r.flows),
                       "attack_flows": int(r.attack_flows), "category": cats[int(r.top_cat)],
                       "wrong": int(r.wrong), "predicted": cats[int(r.pred_cat)]}
                      for r in agg.itertuples()],
            "model": model_info,
            "truncated": bool(n > max_nodes),
            "note": "Node ids are per-window indices; IP addresses are not exposed.",
        }

    # ------------------------------------------------ incidents / explanations
    def _ips(self):
        if getattr(self, "_ip_cols", None) is None:
            d = pd.read_parquet(processed_dir(self.cfg) / "flows.parquet", columns=["src_ip", "dst_ip", "ts"])
            self._ip_cols = (d["src_ip"].astype(str).to_numpy(), d["dst_ip"].astype(str).to_numpy(), d["ts"].to_numpy())
        return self._ip_cols

    def incidents(self, window_id: int, model: str = "gnn_ewc_replay", threshold: float = 0.0) -> dict:
        """Improvement 3: flagged flows of a window grouped into incidents (with IPs)."""
        from src.product.incidents import build_incidents, incident_metrics
        from src.product.response import propose_action
        g = self.get_window(window_id)
        if g is None:
            raise KeyError(f"window {window_id} not found")
        with self.lock:
            learners = self.active_learners()
            if model not in learners:
                raise KeyError(f"model {model} not loaded")
            probs = learners[model].predict_proba(g)
        src, dst, ts = self._ips()
        fi = g.flow_idx.numpy()
        names = class_names(self.cfg)
        inc = build_incidents(src[fi], dst[fi], probs, names, threshold=threshold, ts=ts[fi], y_cat=g.y.numpy())
        metrics = incident_metrics(inc, g.y.numpy())         # uses ground truth: evaluation info for the demo
        for i in inc:
            i["proposed"] = propose_action(i)
            i["sample_edges"] = i["flow_indices"][:5]           # window-local edge ids, for /explain
            del i["flow_indices"]
        return {"window_id": int(window_id), "model": model, "threshold": threshold,
                "n_flows": int(len(fi)), "flagged_flows": int(sum(i["n_flows"] for i in inc)),
                "metrics": metrics, "incidents": inc}

    def explain(self, window_id: int, edge: int, model: str = "gnn_ewc_replay") -> dict:
        """Improvement 2: why was this flow classified the way it was?"""
        from src.explain.explain import explain_edge, summarize
        g = self.get_window(window_id)
        if g is None:
            raise KeyError(f"window {window_id} not found")
        if not 0 <= edge < g.edge_index.shape[1]:
            raise KeyError(f"edge {edge} out of range")
        with self.lock:
            learners = self.active_learners()
            if model not in learners or learners[model].family == "xgb":
                raise KeyError(f"model {model} cannot be explained (needs a neural model)")
            exp = explain_edge(learners[model], g, int(edge), self.data.feature_columns, self.scaler)
        names = class_names(self.cfg)
        src, dst, _ = self._ips()
        fi = int(g.flow_idx[edge])
        exp.update({"summary": summarize(exp, names), "predicted_label": names[exp["predicted_class"]],
                    "true_label": self.cfg["categories"][int(g.y[edge])], "src_ip": src[fi], "dst_ip": dst[fi],
                    "window_id": int(window_id), "model": model})
        return exp

    def list_windows(self) -> list[dict]:
        """Every cached window with its task, split and attack composition (for the explorer)."""
        if getattr(self, "_window_list", None) is None:
            cats = self.cfg["categories"]
            rows = []
            for t in range(self.data.n_tasks):
                for split in ("train", "val", "test"):
                    for g in self.data.graphs(t, split):
                        y = g.y.numpy()
                        counts = np.bincount(y, minlength=len(cats))
                        attack = counts[1:]
                        rows.append({"window_id": int(g.window_id), "task_id": t,
                                     "task_category": self.data.task_categories[t], "split": split,
                                     "n_edges": int(len(y)), "n_nodes": int(g.num_nodes),
                                     "n_attack": int(attack.sum()),
                                     "top_attack": cats[1 + int(attack.argmax())] if attack.sum() else None,
                                     "start": g.window_start})
            self._window_list = sorted(rows, key=lambda r: r["window_id"])
        return self._window_list

    # ------------------------------------------------------------------ demo
    def start_demo(self, delay_seconds: float = 0.5, eval_every: int = 10, max_windows: int | None = None) -> str:
        with self.lock:
            if self.demo is not None and self.demo.is_alive():
                raise RuntimeError("demo already running")
            self.demo = DemoRunner(self, delay_seconds, eval_every, max_windows)
            self.demo.start()
            return self.demo.run_id

    def stop_demo(self) -> bool:
        if self.demo is None:
            return False
        self.demo.stop_event.set()
        return True

    def request_retrain(self) -> dict:
        if self.demo is None or not self.demo.is_alive():
            return {"accepted": False, "reason": "no live stream running; start one with POST /demo/start"}
        self.demo.retrain_requested.set()
        return {"accepted": True, "run_id": self.demo.run_id}


class DemoRunner(threading.Thread):
    """Replays the chronological stream through several models, writing every
    per-window record, drift event and evaluation into the database."""

    def __init__(self, svc: MLService, delay: float, eval_every: int, max_windows: int | None):
        super().__init__(daemon=True)
        self.svc, self.delay, self.eval_every, self.max_windows = svc, delay, eval_every, max_windows
        self.run_id = f"demo-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.stop_event = threading.Event()
        self.retrain_requested = threading.Event()
        self.runners: list[StreamRunner] = []
        self.ready = False  # True once every runner is warm-started or trained on task 1
        self.status = "initialising"
        self.position = 0
        self.total = 0
        self.error: str | None = None

    def _db(self, rows: list) -> None:
        if not self.svc.Session:
            return
        with self.svc.Session() as s:
            s.add_all(rows)
            s.commit()

    def _on_window(self, row):
        self._db([WindowStat(run_id=self.run_id, model_name=row["model"], stream_index=row["stream_index"],
                             window_id=row["window_id"], task_id=row["task_id"], n_flows=row["n_flows"],
                             error_rate=row["error_rate"], pred_benign=row["pred_benign"],
                             pred_known_attack=row["pred_known_attack"], pred_novel_drifted=row["pred_novel_drifted"],
                             true_attack_fraction=row["true_attack_fraction"], drift_flag=row["drift_flag"],
                             retrained=row["retrained"], ts=_utc(row["ts"]))])

    def _on_drift(self, ev):
        self._db([DriftEventRow(run_id=self.run_id, detector=ev["detector"], prev_error=_nan(ev["prev_error"]),
                                new_error=_nan(ev["new_error"]), triggered_retrain=ev["triggered_retrain"],
                                model_name=ev["model"], stream_index=ev["stream_index"], window_id=ev["window_id"],
                                reason=ev["reason"], ts=_utc(ev["ts"]))])

    def _on_eval(self, row):
        self._db([Metric(run_id=self.run_id, source="stream", model_name=row["model"], policy=row["policy"],
                         stream_index=row["stream_index"], task_id=row["seen_tasks"] - 1,
                         accuracy=_nan(row["accuracy_seen"]), macro_f1=_nan(row["macro_f1_seen"]),
                         retention_rate=_nan(row["retention_rate"]), fpr=_nan(row["fpr_seen"]),
                         retrains_so_far=row["retrains_so_far"],
                         ts=_utc(row["ts"]) if row["ts"] else datetime.now(timezone.utc))])

    def run(self):
        try:
            cfg, data = self.svc.cfg, self.svc.data
            node_in = data.graphs(0, "train")[0].x.shape[1]
            for model, policy in DEMO_RUNS:
                set_seed(cfg["seed"])
                learner = make_learner(model, cfg, data.meta["n_features"], num_classes(cfg), self.svc.device,
                                       node_in=node_in)
                self.runners.append(StreamRunner(cfg, data, learner, policy=policy, eval_every=self.eval_every,
                                                 on_window=self._on_window, on_drift=self._on_drift,
                                                 on_eval=self._on_eval))
            self.warm_started = {}
            for r in self.runners:
                warm = self.svc.warm_start(r.learner, task=0)
                self.warm_started[r.learner.name] = warm
                self.status = "evaluating task-1 checkpoints" if warm else "training on task 1"
                with self.svc.lock:
                    r.start(pretrained=warm)
            stream = self.runners[0].stream_graphs()
            if self.max_windows:
                stream = stream[: self.max_windows]
            self.total = len(stream)
            self.ready = True
            self.status = "streaming"
            for k, g in enumerate(stream):
                if self.stop_event.is_set():
                    self.status = "stopped"
                    return
                manual = self.retrain_requested.is_set()
                self.retrain_requested.clear()
                with self.svc.lock:
                    for r in self.runners:
                        r.step(k, g)
                        if manual and r.manual_adapt(tag=f"manual_w{int(g.window_id)}"):
                            self._on_drift({"detector": "manual", "prev_error": None, "new_error": None,
                                            "triggered_retrain": True, "model": r.learner.name, "stream_index": k,
                                            "window_id": int(g.window_id), "reason": "POST /retrain",
                                            "ts": g.window_start})
                self.position = k + 1
                time.sleep(self.delay)
            with self.svc.lock:
                for r in self.runners:
                    r.finish(stream[-1] if stream else None, len(stream))
            self.status = "finished"
        except Exception as exc:  # surfaced through /demo/status
            log.exception("demo failed")
            self.error = repr(exc)
            self.ready = False
            self.status = "failed"

    def describe(self) -> dict:
        return {"run_id": self.run_id, "status": self.status, "position": self.position, "total": self.total,
                "error": self.error, "alive": self.is_alive(),
                "warm_started": getattr(self, "warm_started", {}),
                "retrains": {r.learner.name: r.retrains for r in self.runners}}


def _nan(v):
    try:
        return None if v is None or not np.isfinite(float(v)) else float(v)
    except (TypeError, ValueError):
        return None
