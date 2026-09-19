"""Read-only access to the committed experiment outputs in results/ for the dashboard.

Every value served here is read from a file written by an experiment script;
nothing is computed or estimated on the fly beyond reshaping. Missing
experiments return 404 so the UI can show "not run yet" instead of a number.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from src.utils.config import REPO_ROOT

RESULTS = REPO_ROOT / "results"
DATASETS = ("cicids2017", "csecicids2018")
MODES = ("multiclass", "binary")
SAFE = {"dataset": DATASETS, "mode": MODES}

router = APIRouter(prefix="/results", tags=["results"])


def _check(dataset: str, mode: str | None = None) -> Path:
    if dataset not in DATASETS or (mode is not None and mode not in MODES):
        raise HTTPException(422, f"dataset must be one of {DATASETS}, mode one of {MODES}")
    return RESULTS / dataset / (mode or "")


def _records(df: pd.DataFrame) -> list[dict]:
    """JSON-safe records (NaN/inf -> None)."""
    out = []
    for row in df.to_dict(orient="records"):
        out.append({k: (None if isinstance(v, float) and not math.isfinite(v) else
                        (v.item() if isinstance(v, np.generic) else v)) for k, v in row.items()})
    return out


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        try:
            shown = path.relative_to(RESULTS.parent)
        except ValueError:          # results/ may live elsewhere (junction, test dir)
            shown = path.name
        raise HTTPException(404, f"{shown} not found (experiment not run yet)")
    return pd.read_csv(path)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@router.get("/index")
def index():
    """Which experiments exist on disk, per dataset and label mode."""
    out = {}
    for ds in DATASETS:
        for mode in MODES:
            base = RESULTS / ds / mode
            if not base.exists():
                continue
            out.setdefault(ds, {})[mode] = {
                exp: (base / exp / marker).exists()
                for exp, marker in [("continual", "summary.csv"), ("drift", "summary.csv"), ("loao", "loao.csv"),
                                    ("ip_remap", "summary.csv"), ("ewc_lambda_sweep", "sweep.csv"),
                                    ("tuning", "tuning.csv"), ("open_set", "open_set.csv"),
                                    ("conformal", "conformal.csv"), ("incidents", "incidents.csv")]
            }
    return out


@router.get("/continual")
def continual(dataset: str = "cicids2017", mode: str = "multiclass"):
    base = _check(dataset, mode) / "continual"
    mean = _read_csv(base / "summary.csv")
    if "ip_mode" in mean:
        mean = mean[mean["ip_mode"] == "none"]
    std = pd.read_csv(base / "summary_std.csv") if (base / "summary_std.csv").exists() else None
    if std is not None and "ip_mode" in std:
        std = std[std["ip_mode"] == "none"]
    models = list(dict.fromkeys(mean["model"]))
    recall = {}
    for m in models:
        f = base / f"recall_matrix_{m}.csv"
        if f.exists():
            R = pd.read_csv(f, index_col=0)
            recall[m] = {"rows": list(R.index), "cols": list(R.columns),
                         "values": [[None if not np.isfinite(v) else float(v) for v in row] for row in R.to_numpy()]}
    forgetting = {}
    seeds = (_read_json(base / "seeds.json") or {}).get("seeds", [])
    for m in models:
        vals = [_read_json(base / f"seed{s}" / f"forgetting_{m}.json") for s in seeds]
        vals = [v for v in vals if v]
        if vals:
            forgetting[m] = {k: float(np.nanmean([v[k] for v in vals])) for k in vals[0]}
    tasks = mean.drop_duplicates("after_task").sort_values("after_task")["task_category"].tolist()
    return {"dataset": dataset, "mode": mode, "seeds": seeds, "models": models, "tasks": tasks,
            "summary": _records(mean), "summary_std": _records(std) if std is not None else [],
            "recall_matrix": recall, "forgetting": forgetting}


@router.get("/confusion")
def confusion(dataset: str = "cicids2017", mode: str = "multiclass", model: str = "gnn_ewc_replay",
              after_task: int = Query(6, ge=0, le=20), seed: int = 42):
    base = _check(dataset, mode) / "continual" / f"seed{seed}" / "confusion" / model
    if not base.parent.exists() or "/" in model or "\\" in model or ".." in model:
        raise HTTPException(404, "unknown model")
    df = _read_csv(base / f"after_task{after_task}_seen.csv")
    df = df.set_index(df.columns[0])
    return {"labels": [c.replace("pred_", "") for c in df.columns], "matrix": df.to_numpy().astype(int).tolist(),
            "model": model, "after_task": after_task, "seed": seed}


@router.get("/drift")
def drift(dataset: str = "cicids2017", mode: str = "multiclass"):
    base = _check(dataset, mode) / "drift"
    summary = _read_csv(base / "summary.csv")
    ev = pd.read_csv(base / "stream_eval.csv") if (base / "stream_eval.csv").exists() else pd.DataFrame()
    win = pd.read_csv(base / "stream_windows.csv") if (base / "stream_windows.csv").exists() else pd.DataFrame()
    de = pd.read_csv(base / "drift_events.csv") if (base / "drift_events.csv").exists() else pd.DataFrame()
    keep = ["model", "policy", "stream_index", "window_id", "task_id", "error_rate", "true_attack_fraction",
            "drift_flag", "retrained", "pred_benign", "pred_known_attack", "pred_novel_drifted"]
    return {"summary": _records(summary), "eval": _records(ev),
            "windows": _records(win[[c for c in keep if c in win]]) if len(win) else [],
            "events": _records(de) if len(de) else []}


@router.get("/loao")
def loao(dataset: str = "cicids2017", mode: str = "binary"):
    return {"rows": _records(_read_csv(_check(dataset, mode) / "loao" / "loao.csv"))}


@router.get("/ip_remap")
def ip_remap(dataset: str = "cicids2017", mode: str = "multiclass"):
    df = _read_csv(_check(dataset, mode) / "ip_remap" / "summary.csv")
    last = df[df["after_task"] == df["after_task"].max()]
    return {"final": _records(last), "all": _records(df)}


@router.get("/tuning")
def tuning(dataset: str = "cicids2017"):
    base = _check(dataset, "multiclass")
    out = {}
    if (base / "tuning" / "tuning.csv").exists():
        out["tuning"] = _records(pd.read_csv(base / "tuning" / "tuning.csv"))
    if (base / "ewc_lambda_sweep" / "sweep.csv").exists():
        out["sweep"] = _records(pd.read_csv(base / "ewc_lambda_sweep" / "sweep.csv"))
    out["selected_ewc"] = _read_json(base / "ewc_lambda_sweep" / "selected.json")
    sel = base / "tuning" / "selected.yaml"
    out["selected_tuning"] = sel.read_text(encoding="utf-8") if sel.exists() else None
    if not out.get("tuning") and not out.get("sweep"):
        raise HTTPException(404, "no tuning results")
    return out


@router.get("/open_set")
def open_set(dataset: str = "cicids2017"):
    """Improvement 6: novelty-detection scores on the next (unseen) task, plus proposed-category clusters."""
    base = _check(dataset, "multiclass") / "open_set"
    clusters = pd.read_csv(base / "clusters.csv") if (base / "clusters.csv").exists() else pd.DataFrame()
    return {"rows": _records(_read_csv(base / "open_set.csv")), "clusters": _records(clusters) if len(clusters) else []}


@router.get("/conformal")
def conformal(dataset: str = "cicids2017"):
    """Improvement 7: class-conditional conformal abstention."""
    base = _check(dataset, "multiclass") / "conformal"
    per = pd.read_csv(base / "per_class.csv") if (base / "per_class.csv").exists() else pd.DataFrame()
    return {"rows": _records(_read_csv(base / "conformal.csv")), "per_class": _records(per) if len(per) else []}


@router.get("/incidents")
def incidents(dataset: str = "cicids2017"):
    """Improvement 3: alert -> incident compression under a false-alarm budget."""
    base = _check(dataset, "multiclass") / "incidents"
    return {"rows": _records(_read_csv(base / "incidents.csv"))}


@router.get("/adaptation")
def adaptation(dataset: str = "cicids2017"):
    """Improvements 4 + 8: gated adaptation and label-budgeted (active-learning) streams, next to the baseline."""
    base = _check(dataset, "multiclass")
    out = {}
    for name in ("drift", "drift_gate", "drift_al100", "drift_al100_hybrid", "drift_al20", "drift_labelfree_al100"):
        f = base / name / "summary.csv"
        if f.exists():
            out[name] = _records(pd.read_csv(f))
    if len(out) <= 1:
        raise HTTPException(404, "adaptation variants not run yet")
    return out


@router.get("/run_info")
def run_info(dataset: str = "cicids2017", mode: str = "multiclass", experiment: str = "continual"):
    if experiment not in ("continual", "drift", "loao", "ip_remap", "ewc_lambda_sweep", "tuning", "open_set",
                          "conformal", "incidents"):
        raise HTTPException(422, "unknown experiment")
    info = _read_json(_check(dataset, mode) / experiment / "run_info.json")
    if info is None:
        raise HTTPException(404, "run_info.json not found")
    return info


@router.get("/data_summary")
def data_summary(dataset: str = "cicids2017"):
    """Task segmentation and per-split counts from the processed-data metadata."""
    from src.preprocessing.pipeline import processed_dir
    from src.utils.config import load_config
    cfg = load_config(dataset)
    d = processed_dir(cfg)
    meta = _read_json(d / "meta.json")
    if meta is None:
        raise HTTPException(404, "processed data not found")
    counts = pd.read_csv(d / "counts_task_split_category.csv") if (d / "counts_task_split_category.csv").exists() \
        else pd.DataFrame()
    segs = pd.read_csv(d / "segments.csv") if (d / "segments.csv").exists() else pd.DataFrame()
    return {"n_flows": meta["n_flows"], "n_windows": meta["n_windows"], "n_features": meta["n_features"],
            "task_categories": meta["task_categories"], "feature_columns": meta["feature_columns"],
            "clean_stats": meta.get("clean_stats"), "counts": _records(counts), "segments": _records(segs),
            "flow_sample_fraction": cfg["preprocessing"].get("flow_sample_fraction", 1.0)}
