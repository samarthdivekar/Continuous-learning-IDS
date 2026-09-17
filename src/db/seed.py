"""Load committed results + window metadata into the database.

    python -m src.db.seed --dataset cicids2017 --label-mode multiclass

Everything inserted comes from files in results/ (produced by the experiment
scripts) or from the processed-data metadata. Nothing is generated here.
Re-running replaces the rows of the same run_id.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from sqlalchemy import delete

from src.db.models import DriftEventRow, GraphWindow, Metric, WindowStat
from src.db.session import get_sessionmaker
from src.graph.window_builder import SPLIT_NAMES, graph_cache_dir
from src.preprocessing.pipeline import processed_dir
from src.utils.config import load_config, resolve_path
from src.utils.logging import get_logger

log = get_logger(__name__)


def _f(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def _ts(v):
    t = pd.Timestamp(v) if v not in (None, "", np.nan) and not pd.isna(v) else pd.Timestamp.now(tz="UTC")
    return (t.tz_localize("UTC") if t.tzinfo is None else t).to_pydatetime()


def seed(dataset: str, label_mode: str, Session=None) -> dict:
    cfg = load_config(dataset, [f"label_mode={label_mode}"])
    Session = Session or get_sessionmaker()
    base = resolve_path(cfg, "results") / dataset / label_mode
    counts = {}
    with Session() as s:
        # task-sequence results
        f = base / "continual" / "summary.csv"
        if f.exists():
            run_id = f"continual:{dataset}:{label_mode}"
            s.execute(delete(Metric).where(Metric.run_id == run_id))
            df = pd.read_csv(f)
            if "ip_mode" in df:
                df = df[df["ip_mode"] == "none"]
            for r in df.itertuples():
                s.add(Metric(run_id=run_id, source="continual", model_name=r.model, task_id=int(r.after_task),
                             accuracy=_f(r.accuracy_seen), macro_f1=_f(r.macro_f1_seen),
                             retention_rate=_f(r.retention_rate), fpr=_f(r.fpr_seen)))
            counts["continual_metrics"] = len(df)
        # recorded drift experiment (so the dashboard has a stream even before a live demo)
        d = base / "drift"
        if (d / "stream_eval.csv").exists():
            run_id = f"experiment:{dataset}:{label_mode}"
            for model in (Metric, DriftEventRow, WindowStat):
                s.execute(delete(model).where(model.run_id == run_id))
            ev = pd.read_csv(d / "stream_eval.csv")
            for r in ev.itertuples():
                s.add(Metric(run_id=run_id, source="stream", model_name=r.model, policy=r.policy,
                             stream_index=int(r.stream_index), task_id=int(r.seen_tasks) - 1,
                             accuracy=_f(r.accuracy_seen), macro_f1=_f(r.macro_f1_seen),
                             retention_rate=_f(r.retention_rate), fpr=_f(r.fpr_seen),
                             retrains_so_far=int(r.retrains_so_far), ts=_ts(r.ts)))
            if (d / "drift_events.csv").exists():
                de = pd.read_csv(d / "drift_events.csv")
                for r in de.itertuples():
                    s.add(DriftEventRow(run_id=run_id, detector=r.detector, prev_error=_f(r.prev_error),
                                        new_error=_f(r.new_error), triggered_retrain=bool(r.triggered_retrain),
                                        model_name=f"{r.model}:{r.policy}" if r.policy not in ("adwin",) else r.model,
                                        stream_index=int(r.stream_index), window_id=int(r.window_id),
                                        reason=r.reason, ts=_ts(r.ts)))
            sw = pd.read_csv(d / "stream_windows.csv")
            sw = sw[sw["policy"].isin(["adwin", "never"])]
            for r in sw.itertuples():
                s.add(WindowStat(run_id=run_id, model_name=r.model, stream_index=int(r.stream_index),
                                 window_id=int(r.window_id), task_id=int(r.task_id), n_flows=int(r.n_flows),
                                 error_rate=float(r.error_rate), pred_benign=int(r.pred_benign),
                                 pred_known_attack=int(r.pred_known_attack),
                                 pred_novel_drifted=int(r.pred_novel_drifted),
                                 true_attack_fraction=float(r.true_attack_fraction), drift_flag=bool(r.drift_flag),
                                 retrained=bool(r.retrained), ts=_ts(r.ts)))
            counts["stream_eval_rows"] = len(ev)
        # graph windows
        pdir = processed_dir(cfg)
        if (pdir / "flows.parquet").exists():
            flows = pd.read_parquet(pdir / "flows.parquet", columns=["ts", "src_ip", "dst_ip", "window_id",
                                                                    "task_id", "split"])
            flows["src_ip"] = flows["src_ip"].astype(str)
            flows["dst_ip"] = flows["dst_ip"].astype(str)
            agg = flows.groupby("window_id").agg(start=("ts", "min"), end=("ts", "max"), n_edges=("ts", "size"),
                                                 task_id=("task_id", "first"), split=("split", "first"))
            nodes = pd.concat([flows[["window_id", "src_ip"]].rename(columns={"src_ip": "ip"}),
                               flows[["window_id", "dst_ip"]].rename(columns={"dst_ip": "ip"})]) \
                .drop_duplicates().groupby("window_id").size()
            gdir = graph_cache_dir(cfg, resolve_path(cfg, "cache"))
            s.execute(delete(GraphWindow))
            for wid, r in agg.iterrows():
                split = SPLIT_NAMES[int(r["split"])]
                s.add(GraphWindow(id=int(wid), window_start=_ts(r["start"]), window_end=_ts(r["end"]),
                                  n_nodes=int(nodes[wid]), n_edges=int(r["n_edges"]), task_id=int(r["task_id"]),
                                  split=split, cache_path=str(gdir / f"task{int(r['task_id'])}_{split}.pt")))
            counts["graph_windows"] = len(agg)
        s.commit()
    log.info("seeded: %s", counts)
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", default="cicids2017")
    p.add_argument("--label-mode", default="multiclass")
    a = p.parse_args()
    seed(a.dataset, a.label_mode)


if __name__ == "__main__":
    main()
