"""Drift-driven streaming simulation (brief §5.5, Phase 7).

Protocol
  1. Every model is trained on task 0's training windows ("deployment day").
  2. The training windows of tasks 1..T-1 are replayed as a single
     chronological stream (no task boundaries are revealed to the model).
  3. For each incoming window the model predicts first (logged), then the
     window's labels become available (delayed-label assumption) and the
     monitored signal is fed to the adaptation policy.
  4. Policies:
       adwin     adapt only when ADWIN flags an increase in error  (ours)
       periodic  adapt every `periodic_every` windows               (comparison)
       oracle    adapt at each true task boundary (on that task's windows)
       never     never adapt                                        (lower bound)
     An adaptation cycle trains on the most recent `adapt_windows` windows with
     the learner's own strategy (EWC/replay for ours; nothing for naive), then
     EWC consolidates, exactly as after a task in the task-sequence experiment.
  5. Every `eval_every` windows, and at every task boundary, the model is
     evaluated on held-out TEST windows of all tasks whose windows have
     appeared in the stream so far -> accuracy / retention / FPR over time,
     alongside the cumulative retrain count.

The same `StreamRunner` powers the live dashboard demo (src/api/demo.py),
which writes the identical records into the database instead of CSV.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from src.drift.adwin_monitor import ADWINMonitor
from src.evaluation.continual import _concat, predict_graphs
from src.evaluation.metrics import category_recall, core_metrics
from src.graph.window_builder import edge_labels
from src.training.learners import BaseLearner

NOVEL_CONFIDENCE = 0.6  # predictions below this max-probability are shown as "Novel / Drifted"


@dataclass
class StreamRunner:
    cfg: dict
    data: object
    learner: BaseLearner
    policy: str = "adwin"
    eval_every: int = 10
    on_window: Callable[[dict], None] | None = None
    on_drift: Callable[[dict], None] | None = None
    on_eval: Callable[[dict], None] | None = None
    window_rows: list = field(default_factory=list)
    eval_rows: list = field(default_factory=list)
    drift_events: list = field(default_factory=list)
    retrains: int = 0

    def __post_init__(self):
        d = self.cfg["drift"]
        self.monitor = ADWINMonitor(d["delta"], d["min_windows_between"])
        self.recent: deque = deque(maxlen=int(d["adapt_windows"]))
        self.mode = self.cfg["label_mode"]
        cats = self.cfg["categories"]
        self.task0_cat = cats.index(self.data.task_categories[0])
        self.test = {t: self.data.graphs(t, "test") for t in range(self.data.n_tasks)}

    # ------------------------------------------------------------------
    def stream_graphs(self) -> list:
        gs = [g for t in range(1, self.data.n_tasks) for g in self.data.graphs(t, "train")]
        return sorted(gs, key=lambda g: g.window_id)

    def evaluate(self, stream_index: int, seen_tasks: set[int], window_id: int, ts: str) -> dict:
        preds = {t: predict_graphs(self.learner, self.test[t], self.mode) for t in sorted(seen_tasks)}
        seen = _concat(list(preds.values()))
        m = core_metrics(seen["y_true"], seen["y_pred"], self.mode)
        row = {"model": self.learner.name, "policy": self.policy, "stream_index": stream_index,
               "window_id": window_id, "ts": ts, "seen_tasks": len(seen_tasks),
               "accuracy_seen": m["accuracy"], "macro_f1_seen": m["macro_f1"], "fpr_seen": m["fpr"],
               "detection_rate_seen": m["detection_rate"],
               "retention_rate": category_recall(preds[0]["y_cat"], preds[0]["y_pred"], self.task0_cat, self.mode),
               "retrains_so_far": self.retrains}
        self.eval_rows.append(row)
        if self.on_eval:
            self.on_eval(row)
        return row

    def adapt(self, graphs: list, tag: str) -> None:
        # epochs=None -> the learner's tuned per-task epochs
        self.learner.learn(list(graphs), tag=tag, epochs=self.cfg["drift"].get("adapt_epochs"))
        self.retrains += 1
        self.monitor.notify_adapted()

    def run(self, max_windows: int | None = None) -> None:
        stream = self.stream_graphs()
        if max_windows:
            stream = stream[:max_windows]
        self.start()
        for k, g in enumerate(stream):
            self.step(k, g)
        self.finish(stream[-1] if stream else None, len(stream))

    # Step-wise API (used by the live demo to interleave several models) ------
    def start(self) -> None:
        self.learner.learn(self.data.graphs(0, "train"), tag="initial_task0")
        self.seen_tasks = {0}
        self.prev_task = 0
        self.task_windows: list = []
        self.evaluate(-1, self.seen_tasks, -1, "")

    def finish(self, last, n: int) -> None:
        if self.policy == "oracle" and self.task_windows and self.learner.adapts:
            self.adapt(self.task_windows, tag=f"oracle_task{self.prev_task}")
        self.evaluate(n, self.seen_tasks, int(last.window_id) if last is not None else -1,
                      last.window_end if last is not None else "")

    def step(self, k: int, g) -> dict:
        """Process stream window number `k`: predict, log, monitor, maybe adapt."""
        task = int(g.task_id)
        if task != self.prev_task:
            if self.policy == "oracle" and self.task_windows and self.learner.adapts:
                self.adapt(self.task_windows, tag=f"oracle_task{self.prev_task}")
            self.evaluate(k, self.seen_tasks, int(g.window_id), g.window_start)
            self.task_windows.clear()
            self.prev_task = task
        self.seen_tasks.add(task)

        # 1) predict BEFORE labels are revealed
        probs = self.learner.predict_proba(g)
        pred = probs.argmax(1)
        conf = probs.max(1)
        # 2) delayed labels arrive -> monitored signal
        y = edge_labels(g, self.mode).numpy()
        err = float((pred != y).mean())
        signal = err if self.cfg["drift"]["signal"] == "error" else float(1.0 - conf.mean())
        low_conf = conf < NOVEL_CONFIDENCE
        row = {"model": self.learner.name, "policy": self.policy, "stream_index": k,
               "window_id": int(g.window_id), "task_id": task, "ts": g.window_start,
               "n_flows": len(y), "error_rate": err, "signal": signal,
               "true_attack_fraction": float((g.y.numpy() > 0).mean()),
               "pred_benign": int(((pred == 0) & ~low_conf).sum()),
               "pred_known_attack": int(((pred != 0) & ~low_conf).sum()),
               "pred_novel_drifted": int(low_conf.sum()),
               "drift_flag": False, "retrained": False}
        self.recent.append(g)
        self.task_windows.append(g)

        # 3) policy decides whether to adapt
        trigger = False
        if self.policy == "adwin" and self.learner.adapts:
            ev = self.monitor.update(signal, k, int(g.window_id), g.window_start)
            if ev is not None:
                row["drift_flag"] = True
                evd = {**ev.__dict__, "model": self.learner.name}
                if self.on_drift:
                    self.on_drift(evd)
                self.drift_events.append(evd)
                trigger = ev.triggered_retrain
        elif self.policy == "periodic" and self.learner.adapts:
            trigger = (k + 1) % int(self.cfg["drift"]["periodic_every"]) == 0
        if trigger:
            self.adapt(self.recent, tag=f"{self.policy}_w{int(g.window_id)}")
            row["retrained"] = True
        row["retrains_so_far"] = self.retrains
        self.window_rows.append(row)
        if self.on_window:
            self.on_window(row)
        if self.eval_every and (k + 1) % self.eval_every == 0:
            self.evaluate(k, self.seen_tasks, int(g.window_id), g.window_end)
        self.last_pred = pred
        self.last_conf = conf
        return row

    def manual_adapt(self, tag: str = "manual") -> bool:
        """Adaptation cycle requested from outside (POST /retrain in the demo)."""
        if not self.learner.adapts or not self.recent:
            return False
        self.adapt(self.recent, tag=tag)
        return True

    def frames(self) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        return pd.DataFrame(self.window_rows), pd.DataFrame(self.eval_rows), pd.DataFrame(self.drift_events)
