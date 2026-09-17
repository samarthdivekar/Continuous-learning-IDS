"""Test fixtures.

The synthetic flows below exist ONLY to exercise code paths in unit tests.
They are never written to results/ and no reported number comes from them.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.utils.config import load_config


@pytest.fixture
def cfg(tmp_path):
    c = load_config("cicids2017", [
        f"paths.processed={tmp_path / 'processed'}",
        f"paths.cache={tmp_path / 'cache'}",
        f"paths.results={tmp_path / 'results'}",
        "window.flows_per_window=50",
        "train.device=cpu",
        "train.gnn_epochs=1",
        "train.ffnn_epochs=1",
        "ewc.fisher_batches=3",
        "graph.hidden=16",
        "ffnn.hidden=[16]",
        "xgboost.n_estimators=5",
        "drift.adapt_windows=3",
        "drift.min_windows_between=1",
    ])
    return c


def synthetic_raw_csv(path, n_benign=1200, seed=0):
    """Write a tiny CSV in the corrected-CIC header format with three attack bursts."""
    rng = np.random.default_rng(seed)
    t0 = pd.Timestamp("2017-07-04 12:00:00")
    rows = []

    def add(ts, src, dst, label, attempted=-1, scale=1.0):
        rows.append({
            "id": len(rows), "Flow ID": f"{src}-{dst}", "Src IP": src, "Src Port": int(rng.integers(1024, 65000)),
            "Dst IP": dst, "Dst Port": 80, "Protocol": 6, "Timestamp": str(ts),
            "Flow Duration": float(rng.exponential(1000) * scale), "Total Fwd Packet": float(rng.integers(1, 50)),
            "Total Bwd packets": float(rng.integers(0, 50)), "Flow Bytes/s": float(rng.exponential(100) * scale),
            "Label": label, "Attempted Category": attempted,
        })

    for i in range(n_benign):
        add(t0 + pd.Timedelta(seconds=i * 20), f"192.168.10.{rng.integers(1, 30)}", f"10.0.0.{rng.integers(1, 20)}", "BENIGN")
    for i in range(80):  # brute force burst (fan-in to one server)
        add(t0 + pd.Timedelta(minutes=30, seconds=i), "205.174.165.73", "192.168.10.50", "FTP-Patator", scale=0.1)
    add(t0 + pd.Timedelta(minutes=31), "205.174.165.73", "192.168.10.50", "FTP-Patator - Attempted", attempted=0)
    add(t0 + pd.Timedelta(minutes=31, seconds=1), "205.174.165.73", "192.168.10.50", "FTP-Patator - Attempted", attempted=0)
    for i in range(80):  # DoS burst, later
        add(t0 + pd.Timedelta(hours=3, seconds=i), "205.174.165.73", "192.168.10.51", "DoS Hulk", scale=50)
    for i in range(80):  # port scan burst: fan-out from one host
        add(t0 + pd.Timedelta(hours=6, seconds=i), "205.174.165.73", f"192.168.10.{i % 250}", "Portscan", scale=0.01)
    df = pd.DataFrame(rows)
    # an inf value, a NaN and an exact duplicate row
    df.loc[3, "Flow Bytes/s"] = np.inf
    df.loc[4, "Flow Bytes/s"] = np.nan
    df = pd.concat([df, df.iloc[[5]]], ignore_index=True)
    df.to_csv(path, index=False)
    return df
