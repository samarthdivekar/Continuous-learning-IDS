"""End-to-end data preparation: raw CSV -> processed flow table -> cached graphs.

Output layout (key = hash of every config value that affects the data):
    data/processed/<dataset>_<key>/flows.parquet   scaled flow table (+ task/window/split)
    data/processed/<dataset>_<key>/meta.json       feature list, task order, counts, cleaning stats
    data/processed/<dataset>_<key>/scaler.json     task-1 scaler parameters
    cache/graphs/<dataset>_<key>/task<t>_<split>.pt  list[torch_geometric.data.Data]
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.graph.window_builder import (SPLIT_CODES, assign_windows_and_splits, cache_key,
                                      graph_cache_dir, graphs_from_table, load_graphs, save_graphs)
from src.ingestion.loader import ensure_extracted, list_csvs, load_flows
from src.preprocessing.clean import clean_flows, feature_columns
from src.preprocessing.scaling import FeatureScaler
from src.preprocessing.tasks import assign_tasks, find_segments, segments_table
from src.utils.config import resolve_path
from src.utils.logging import get_logger

log = get_logger(__name__)


def processed_dir(cfg: dict) -> Path:
    return resolve_path(cfg, "processed") / f"{cfg['dataset']}_{cache_key(cfg)}"


def prepare_dataset(cfg: dict, force: bool = False, csv_files: list[Path] | None = None) -> Path:
    out = processed_dir(cfg)
    if (out / "meta.json").exists() and not force:
        log.info("Processed data already present at %s (use --force to rebuild)", out)
        return out
    out.mkdir(parents=True, exist_ok=True)
    pre = cfg["preprocessing"]

    # 1. load ---------------------------------------------------------------
    if csv_files is None:
        folder = ensure_extracted(resolve_path(cfg, "raw"), cfg["dataset_info"])
        csv_files = list_csvs(folder)
    df, load_stats = load_flows(csv_files, pre["attempted_policy"], pre.get("flow_sample_fraction", 1.0),
                                seed=cfg["seed"])
    unknown = set(df["category"].unique()) - set(cfg["categories"])
    if unknown:
        raise ValueError(f"Categories {unknown} not in config categories")

    # 2. clean + chronological order -----------------------------------------
    df, clean_stats = clean_flows(df)
    log.info("Clean stats: %s", clean_stats)

    # 3. tasks ----------------------------------------------------------------
    segments = find_segments(df, pre["segment_gap_seconds"], pre["min_segment_flows"])
    df = assign_tasks(df, segments)
    task_categories: dict[int, str] = {}
    for s in segments:
        task_categories.setdefault(s.task_id, s.category)
    log.info("Task order: %s", [task_categories[t] for t in sorted(task_categories)])

    df["y_multi"] = df["category"].map({c: i for i, c in enumerate(cfg["categories"])}).astype(np.int8)

    # 4. windows + splits -----------------------------------------------------
    df = assign_windows_and_splits(df, cfg["window"], cfg["split"], pre.get("window_fraction"))

    # 5. scale (fit on task 0 train only) --------------------------------------
    feats = feature_columns(df)
    fit_mask = (df["task_id"] == 0) & (df["split"] == SPLIT_CODES["train"])
    scaler = FeatureScaler(pre["clip_value"]).fit(df.loc[fit_mask, feats].to_numpy(), feats)
    df[feats] = scaler.transform(df[feats].to_numpy())
    scaler.save(out / "scaler.json")

    # 6. persist flow table ---------------------------------------------------
    df["src_ip"] = df["src_ip"].astype("category")
    df["dst_ip"] = df["dst_ip"].astype("category")
    df.to_parquet(out / "flows.parquet", index=False)

    counts = (df.groupby(["task_id", "split", "category"]).size()
                .rename("flows").reset_index())
    counts["split"] = counts["split"].map({v: k for k, v in SPLIT_CODES.items()})
    windows = df.groupby(["task_id", "split"])["window_id"].nunique().rename("windows").reset_index()
    windows["split"] = windows["split"].map({v: k for k, v in SPLIT_CODES.items()})
    counts.to_csv(out / "counts_task_split_category.csv", index=False)
    segments_table(segments).to_csv(out / "segments.csv", index=False)

    meta = {
        "dataset": cfg["dataset"], "cache_key": cache_key(cfg), "feature_columns": feats,
        "n_features": len(feats), "task_categories": [task_categories[t] for t in sorted(task_categories)],
        "n_tasks": len(task_categories), "n_flows": len(df), "n_windows": int(df["window_id"].nunique()),
        "windows_per_task_split": windows.to_dict(orient="records"),
        "load_stats": load_stats, "clean_stats": clean_stats, "csv_files": [str(p) for p in csv_files],
    }
    with open(out / "meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, default=str)
    log.info("Wrote %s (%d flows, %d windows, %d features)", out, len(df), meta["n_windows"], len(feats))

    build_graph_cache(cfg, df, feats, force=True)
    return out


def build_graph_cache(cfg: dict, df: pd.DataFrame, feats: list[str], force: bool = False) -> Path:
    gdir = graph_cache_dir(cfg, resolve_path(cfg, "cache"))
    gdir.mkdir(parents=True, exist_ok=True)
    for (task, split), part in df.groupby(["task_id", "split"], sort=True):
        name = {v: k for k, v in SPLIT_CODES.items()}[int(split)]
        path = gdir / f"task{int(task)}_{name}.pt"
        if path.exists() and not force:
            continue
        graphs = graphs_from_table(part, feats, cfg["graph"]["node_features"])
        save_graphs(graphs, path)
        log.info("Cached %d graphs -> %s", len(graphs), path.name)
    return gdir


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
@dataclass
class ProcessedData:
    cfg: dict
    root: Path
    meta: dict
    _df: pd.DataFrame | None = None
    _graphs: dict = field(default_factory=dict)

    @property
    def df(self) -> pd.DataFrame:
        if self._df is None:
            self._df = pd.read_parquet(self.root / "flows.parquet")
        return self._df

    @property
    def feature_columns(self) -> list[str]:
        return self.meta["feature_columns"]

    @property
    def n_tasks(self) -> int:
        return self.meta["n_tasks"]

    @property
    def task_categories(self) -> list[str]:
        return self.meta["task_categories"]

    def tabular(self, task: int, split: str) -> pd.DataFrame:
        d = self.df
        return d[(d["task_id"] == task) & (d["split"] == SPLIT_CODES[split])]

    def graphs(self, task: int, split: str) -> list:
        key = (task, split)
        if key not in self._graphs:
            path = graph_cache_dir(self.cfg, resolve_path(self.cfg, "cache")) / f"task{task}_{split}.pt"
            if not path.exists():
                build_graph_cache(self.cfg, self.df, self.feature_columns)
            self._graphs[key] = load_graphs(path)
        return self._graphs[key]


def load_processed(cfg: dict) -> ProcessedData:
    root = processed_dir(cfg)
    if not (root / "meta.json").exists():
        raise FileNotFoundError(f"{root} missing. Run: python -m experiments.prepare_data --dataset {cfg['dataset']}")
    with open(root / "meta.json", "r", encoding="utf-8") as fh:
        meta = json.load(fh)
    return ProcessedData(cfg, root, meta)
