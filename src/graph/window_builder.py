"""Windowed graph construction: flows -> one PyG `Data` graph per time window.

Graph semantics (E-GraphSAGE style):
  * nodes  = hosts (unique IP addresses inside the window)
  * edges  = flows, directed src -> dst, carrying the scaled CICFlowMeter features
  * labels = per-edge (we classify flows, not hosts)
IP strings are used ONLY to build `edge_index`; they never enter any feature
tensor. Node indices are assigned in first-appearance order inside each
window, so the same IP gets unrelated indices in different windows.

Windows never straddle task (segment) boundaries and keep chronological order.
The window/split assignment is written into the processed flow table so the
tabular models (XGBoost, FFNN) train and test on exactly the same flows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch_geometric.data import Data

from src.utils.logging import get_logger

log = get_logger(__name__)

SPLIT_CODES = {"train": 0, "val": 1, "test": 2}
SPLIT_NAMES = {v: k for k, v in SPLIT_CODES.items()}


# ---------------------------------------------------------------------------
# Window + split assignment (operates on the flow table)
# ---------------------------------------------------------------------------
def _window_local_ids(ts: np.ndarray, window_cfg: dict) -> np.ndarray:
    n = len(ts)
    if window_cfg["mode"] == "count":
        size = int(window_cfg["flows_per_window"])
        ids = np.arange(n) // size
        n_full, rem = divmod(n, size)
        # merge a tiny trailing window into the previous one
        if n_full >= 1 and 0 < rem < window_cfg.get("min_fraction", 0.2) * size:
            ids[ids == n_full] = n_full - 1
        return ids
    if window_cfg["mode"] == "time":
        secs = float(window_cfg["seconds"])
        rel = (ts - ts[0]).astype("timedelta64[us]").astype(np.int64) / 1e6
        raw = np.floor(rel / secs).astype(np.int64)
        # re-index so empty time slots do not create gaps
        _, ids = np.unique(raw, return_inverse=True)
        return ids
    raise ValueError(f"Unknown window mode {window_cfg['mode']!r}")


def temporal_split(ordinal: pd.Series, win_task: pd.Series, tcfg: dict) -> pd.Series:
    """Per-task chronological split. Returns split codes indexed like `ordinal`; gap windows get -1.

    Blocks are carved from the END of each task: the last `1 - train - val` fraction tests, the
    `val` fraction before it validates, and everything earlier trains, with `gap` windows dropped
    between blocks. Carving from the end guarantees every task keeps at least one test and one
    validation window even when it is short; the gap windows come out of the training block,
    which is the largest, so the 70/10/20 proportions bend least there.
    """
    f_train = float(tcfg.get("train", 0.7))
    f_val = float(tcfg.get("val", 0.1))
    f_test = max(0.0, 1.0 - f_train - f_val)
    gap = int(tcfg.get("gap", 1))
    n = win_task.groupby(win_task).transform("size")
    n_test = np.maximum(1, np.round(f_test * n)).astype(int)
    n_val = np.maximum(1, np.round(f_val * n)).astype(int)
    test_start = n - n_test
    val_start = test_start - gap - n_val
    train_end = val_start - gap
    if (train_end < 1).any():
        small = sorted(set(win_task[train_end < 1]))
        raise ValueError(f"temporal split: tasks {small} are too short to hold train, val and test blocks")
    split = pd.Series(-1, index=ordinal.index, dtype=np.int8)               # -1 = gap, dropped
    split[ordinal < train_end] = SPLIT_CODES["train"]
    split[(ordinal >= val_start) & (ordinal < val_start + n_val)] = SPLIT_CODES["val"]
    split[ordinal >= test_start] = SPLIT_CODES["test"]
    return split


def attack_aware_temporal_split(df: pd.DataFrame, ordinal: pd.Series, win_task: pd.Series,
                                task_categories: dict[int, str], tcfg: dict) -> pd.Series:
    """Temporal split over each attack's own active span.

    A plain per-task temporal split fails on bursty data: an attack that happens early in its
    task period has no traffic in the task's last 20%, so it cannot be evaluated at all (on
    CIC-IDS2017 WebAttack and Botnet would have zero test flows, DoS eleven). Here each task's
    windows are divided into those carrying the task's new attack and the rest, and each group is
    split chronologically on its own: the model trains on an attack's earliest windows and is
    tested on its latest, never seeing attack traffic from after the test boundary.
    """
    new_cat = df["task_id"].map(task_categories)
    carries = (df["category"] == new_cat).groupby(df["window_id"]).any().reindex(win_task.index, fill_value=False)
    split = pd.Series(-1, index=win_task.index, dtype=np.int8)
    for flag in (True, False):
        idx = win_task.index[carries.to_numpy() == flag]
        if len(idx) == 0:
            continue
        group_task = win_task.loc[idx]
        group_ord = group_task.groupby(group_task).cumcount()       # order within the group, per task
        split.loc[idx] = temporal_split(group_ord, group_task, tcfg).to_numpy()
    return split


def assign_windows_and_splits(df: pd.DataFrame, window_cfg: dict, split_cfg: dict,
                              window_fraction: float | None = None,
                              task_categories: dict[int, str] | None = None) -> pd.DataFrame:
    """Add `window_id` (global, chronological) and `split` columns.

    `df` must be sorted by ts and carry `segment_id`/`task_id`.
    """
    df = df.copy()
    window_id = np.empty(len(df), dtype=np.int64)
    next_id = 0
    seg = df["segment_id"].to_numpy()
    ts = df["ts"].to_numpy()
    # segments are contiguous blocks because df is time-sorted and segments are time intervals
    starts = np.flatnonzero(np.r_[True, seg[1:] != seg[:-1]])
    ends = np.r_[starts[1:], len(df)]
    for s, e in zip(starts, ends):
        local = _window_local_ids(ts[s:e], window_cfg)
        window_id[s:e] = local + next_id
        next_id += int(local.max()) + 1
    df["window_id"] = window_id

    win_task = df.groupby("window_id", sort=True)["task_id"].first()
    ordinal = win_task.groupby(win_task).cumcount()          # chronological position inside its task
    strategy = split_cfg.get("strategy", "interleaved")
    if strategy == "interleaved":
        # Position modulo `period`: test windows are spread across the whole task period,
        # interleaved with training windows from the same attack session.
        period = int(split_cfg["period"])
        pos = ordinal % period
        split = pd.Series(SPLIT_CODES["train"], index=win_task.index, dtype=np.int8)
        split[pos.isin(split_cfg["val_positions"])] = SPLIT_CODES["val"]
        split[pos.isin(split_cfg["test_positions"])] = SPLIT_CODES["test"]
    elif strategy == "temporal":
        # Train on the past, test on the future: per task, the first `train` fraction of windows
        # trains, the next `val` fraction validates, the rest tests, with `gap` windows dropped
        # between blocks so no test window sits next to a training window.
        split = temporal_split(ordinal, win_task, split_cfg.get("temporal", {}))
    elif strategy == "temporal_attack":
        if task_categories is None:
            raise ValueError("temporal_attack needs the task -> new-attack mapping")
        split = attack_aware_temporal_split(df, ordinal, win_task, task_categories, split_cfg.get("temporal", {}))
    else:
        raise ValueError(f"unknown split.strategy {strategy!r} (interleaved | temporal | temporal_attack)")
    gap = split < 0
    if gap.any():
        df = df[~df["window_id"].isin(split.index[gap])].reset_index(drop=True)
        split = split[~gap]
        log.info("%s split: dropped %d gap windows", strategy, int(gap.sum()))
    df["split"] = df["window_id"].map(split).astype(np.int8)

    if window_fraction:
        # Keep whole blocks so the train/val/test proportions survive.
        period = int(split_cfg.get("period", 10))
        stride = max(1, int(round(1.0 / window_fraction)))
        keep_windows = [w for w in win_task.index[((ordinal // period) % stride) == 0] if w in split.index]
        before = df["window_id"].nunique()
        df = df[df["window_id"].isin(keep_windows)].reset_index(drop=True)
        log.info("window_fraction=%s kept %d/%d windows", window_fraction, df["window_id"].nunique(), before)
    return df


# ---------------------------------------------------------------------------
# Graph construction (one window -> one Data object)
# ---------------------------------------------------------------------------
def node_features(num_nodes: int, edge_index: torch.Tensor, kind: str) -> torch.Tensor:
    """Node features carry no identity. `constant` = E-GraphSAGE default.
    `degree` adds log in/out-degree so fan-out (scans) and fan-in (DDoS) are
    visible even with mean aggregation."""
    ones = torch.ones(num_nodes, 1)
    if kind == "constant":
        return ones
    if kind == "degree":
        src, dst = edge_index
        out_deg = torch.bincount(src, minlength=num_nodes).float()
        in_deg = torch.bincount(dst, minlength=num_nodes).float()
        return torch.cat([ones, torch.log1p(out_deg)[:, None], torch.log1p(in_deg)[:, None]], dim=1)
    raise ValueError(f"Unknown node feature kind {kind!r}")


def build_window_graph(src_ip: np.ndarray, dst_ip: np.ndarray, edge_attr: np.ndarray,
                       y: np.ndarray, node_feature_kind: str = "degree", **meta) -> Data:
    codes, uniques = pd.factorize(np.concatenate([src_ip, dst_ip]), sort=False)
    n_e = len(src_ip)
    edge_index = torch.from_numpy(np.stack([codes[:n_e], codes[n_e:]]).astype(np.int64))
    num_nodes = len(uniques)
    data = Data(
        x=node_features(num_nodes, edge_index, node_feature_kind),
        edge_index=edge_index,
        edge_attr=torch.from_numpy(np.ascontiguousarray(edge_attr, dtype=np.float32)),
        y=torch.from_numpy(np.asarray(y, dtype=np.int64)),
        num_nodes=num_nodes,
    )
    for k, v in meta.items():
        data[k] = v
    return data


def edge_labels(g: Data, label_mode: str) -> torch.Tensor:
    """Graphs store the category id in `y`; binary labels are derived on demand
    so one cache serves both label modes."""
    return (g.y > 0).long() if label_mode == "binary" else g.y


def graphs_from_table(df: pd.DataFrame, feature_cols: list[str], node_feature_kind: str) -> list[Data]:
    """Build graphs for every window in `df`, in chronological window order."""
    graphs = []
    feats = df[feature_cols].to_numpy(dtype=np.float32)
    src = df["src_ip"].to_numpy()
    dst = df["dst_ip"].to_numpy()
    y = df["y_multi"].to_numpy()
    flow_idx = df.index.to_numpy()
    wid = df["window_id"].to_numpy()
    order = np.argsort(wid, kind="stable")
    wid_sorted = wid[order]
    starts = np.flatnonzero(np.r_[True, wid_sorted[1:] != wid_sorted[:-1]])
    ends = np.r_[starts[1:], len(order)]
    ts = df["ts"].to_numpy()
    task = df["task_id"].to_numpy()
    split = df["split"].to_numpy()
    for s, e in zip(starts, ends):
        rows = order[s:e]
        g = build_window_graph(
            src[rows], dst[rows], feats[rows], y[rows], node_feature_kind,
            window_id=int(wid_sorted[s]), task_id=int(task[rows[0]]), split=int(split[rows[0]]),
            window_start=str(ts[rows].min()), window_end=str(ts[rows].max()),
        )
        g.flow_idx = torch.from_numpy(flow_idx[rows].astype(np.int64))
        graphs.append(g)
    return graphs


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------
def cache_key(cfg: dict) -> str:
    pre = dict(cfg["preprocessing"])
    if float(pre.get("flow_sample_fraction", 1.0)) == 1.0:
        # No subsampling. Hash it under the legacy key name so caches and results
        # produced before the benign-thinning option was replaced by label-agnostic
        # flow sampling keep their id (their data is byte-identical: neither option
        # draws random numbers at 1.0). Any real sampling gets a new, distinct key.
        pre.pop("flow_sample_fraction", None)
        pre["benign_keep_fraction"] = 1.0
    split = dict(cfg["split"])
    if split.get("strategy", "interleaved") == "interleaved":
        # The default strategy hashes exactly as before the option existed, so every cache and
        # result produced with interleaved splits keeps its id. Temporal gets a new, distinct key.
        split.pop("strategy", None)
        split.pop("temporal", None)
    relevant = {
        "dataset": cfg["dataset"], "pre": pre, "window": cfg["window"],
        "split": split, "node_features": cfg["graph"]["node_features"],
        "categories": cfg["categories"], "seed": cfg["seed"], "v": 3,
    }
    return hashlib.sha1(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:12]


def graph_cache_dir(cfg: dict, cache_root: Path) -> Path:
    return cache_root / "graphs" / f"{cfg['dataset']}_{cache_key(cfg)}"


def save_graphs(graphs: list[Data], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(graphs, path)


def load_graphs(path: Path) -> list[Data]:
    return torch.load(path, weights_only=False)
