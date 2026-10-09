"""Serving performance envelope: how fast can the deployed system score traffic?

    python -m experiments.benchmark_serving                 # GPU (if present) and CPU
    python -m experiments.benchmark_serving --devices cpu   # one device only

Measures the two operations the console relies on, through the same service layer the API calls:

  predict    score every flow in a window with one model    (backs POST /predict and the console)
  incidents  score + group flagged flows into incidents     (backs GET /incidents/{window})

For each device, on held-out test windows. One-off warm-up is timed separately and excluded from the
per-window rows: service start (imports + models), the window catalogue (which the console requests on
page load and which pulls every window graph into memory) and every flow's IP addresses.

  predict · forward pass        forward pass + response; /predict has no score cache, so this is the
                                model's true per-window scoring rate
  incidents · scores computed   forward pass + grouping flagged flows into incidents
  incidents · scores cached     grouping only (what the console sees on a repeat click); latency only —
                                no flow is scored, so a throughput figure would be meaningless

Reported per row: windows timed, p50 / p95 / mean latency per window, and flows per second
(total flows / total time) where flows were actually scored.

Run it with the GPU otherwise idle: training running in parallel contaminates every number.
Output: results/benchmarks/serving.csv, results/benchmarks/models.csv
"""
from __future__ import annotations

import argparse
import gc
import os
import time

import numpy as np
import pandas as pd
import psutil
import torch

from src.utils.config import REPO_ROOT, load_config
from src.utils.repro import write_run_info

MODEL = "gnn_ewc_replay"


def make_service(device: str):
    """A fresh service on `device`. Imported lazily so the device is set before anything loads."""
    os.environ["DEVICE"] = device
    from src.api.service import MLService, service_config
    svc = MLService(service_config())
    svc.load_models()
    return svc


def time_windows(fn, windows: list[int], repeats: int = 1) -> list[float]:
    out = []
    for wid in windows:
        for _ in range(repeats):
            t0 = time.perf_counter()
            fn(wid)
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            out.append(time.perf_counter() - t0)
    return out


def summarise(device, op, cache, lat: list[float], flows: int) -> dict:
    a = np.asarray(lat)
    return {"device": device, "operation": op, "cache": cache, "windows": len(a),
            "p50_ms": float(np.percentile(a, 50) * 1000), "p95_ms": float(np.percentile(a, 95) * 1000),
            "mean_ms": float(a.mean() * 1000), "flows_timed": int(flows),
            "flows_per_second": float(flows / a.sum()) if a.sum() > 0 else float("nan")}


def run_device(device: str, n_windows: int) -> tuple[list[dict], list[dict]]:
    if device == "cuda" and not torch.cuda.is_available():
        print("no GPU available, skipping cuda")
        return [], []
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    svc = make_service(device)
    startup = time.perf_counter() - t0
    proc = psutil.Process()

    t0 = time.perf_counter()
    catalog = [w for w in svc.list_windows() if w["split"] == "test"]   # loads every window graph
    catalog_load = time.perf_counter() - t0
    t0 = time.perf_counter()
    svc._ips()                      # one-off: every flow's addresses, needed by incidents
    ip_load = time.perf_counter() - t0
    rng = np.random.default_rng(0)
    pick = sorted(rng.choice([w["window_id"] for w in catalog], size=min(n_windows, len(catalog)), replace=False))
    flows = {w["window_id"]: w["n_edges"] for w in catalog}
    total_flows = sum(flows[w] for w in pick)

    def predict(wid):
        svc.predict(window_id=int(wid), models=[MODEL], max_flows_returned=0)

    def incidents(wid):
        svc.incidents(int(wid), MODEL, 0.0)

    rows = []
    svc.invalidate_predictions()
    rows.append(summarise(device, "predict", "forward pass", time_windows(predict, pick, repeats=3), total_flows * 3))
    svc.invalidate_predictions()
    rows.append(summarise(device, "incidents", "scores computed", time_windows(incidents, pick), total_flows))
    cached = summarise(device, "incidents", "scores cached", time_windows(incidents, pick, repeats=3), total_flows * 3)
    cached["flows_per_second"] = float("nan")          # nothing was scored: latency only
    rows.append(cached)
    for r in rows:
        r["service_startup_s"] = startup
        r["ip_columns_load_s"] = ip_load
        r["window_catalogue_load_s"] = catalog_load
        r["process_rss_mb"] = proc.memory_info().rss / 2**20
        r["peak_gpu_mb"] = (torch.cuda.max_memory_allocated() / 2**20) if (device == "cuda" and torch.cuda.is_available()) else 0.0

    models = []
    for name, learner in svc.models.items():
        net = getattr(learner, "model", None)
        params = sum(p.numel() for p in net.parameters()) if hasattr(net, "parameters") else None
        models.append({"device": device, "model": name, "parameters": params})
    return rows, models


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--devices", nargs="*", default=["cuda", "cpu"])
    p.add_argument("--windows", type=int, default=40, help="test windows to time per device")
    args = p.parse_args()

    out = REPO_ROOT / "results" / "benchmarks"
    out.mkdir(parents=True, exist_ok=True)
    rows, models = [], []
    for dev in args.devices:
        r, m = run_device(dev, args.windows)
        rows += r
        models += m
    df = pd.DataFrame(rows)
    df.to_csv(out / "serving.csv", index=False)
    pd.DataFrame(models).drop_duplicates(["model"]).to_csv(out / "models.csv", index=False)
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    write_run_info(out / "run_info.json", load_config("cicids2017"),
                   {"model": MODEL, "windows_per_device": args.windows, "gpu": gpu,
                    "cpu": psutil.cpu_count(logical=False), "cpu_logical": psutil.cpu_count(),
                    "ram_gb": round(psutil.virtual_memory().total / 2**30, 1)})
    cols = ["device", "operation", "cache", "windows", "p50_ms", "p95_ms", "flows_per_second"]
    print(df[cols].to_string(index=False, float_format=lambda v: f"{v:,.1f}"))


if __name__ == "__main__":
    main()
