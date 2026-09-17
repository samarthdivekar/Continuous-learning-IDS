"""CSV flow-record loader.

Reads the (error-corrected) CICFlowMeter CSVs in chunks, normalises column
names, maps labels to categories, applies the attempted-attack policy and the
optional benign thinning, and returns one chronologically sorted DataFrame.

Src/Dst IP are kept as strings: they define graph topology, never features.
"""
from __future__ import annotations

import glob
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from src.ingestion.columns import ID_COLUMNS, normalise_columns
from src.ingestion.labels import build_label_table, is_attempted
from src.utils.logging import get_logger

log = get_logger(__name__)

# Columns that are dropped outright: identifiers, the ephemeral source port
# (random per connection; a known shortcut feature) and Distrinet bookkeeping.
NON_FEATURE_COLUMNS = ID_COLUMNS | {"src_port"}


class ZipMember:
    """A CSV inside a zip archive, read as a stream (the 2018 release is 36 GB
    uncompressed; streaming avoids extracting it)."""

    def __init__(self, archive: Path, member: str):
        self.archive, self.member = Path(archive), member
        self.name = member

    def open(self):
        zf = zipfile.ZipFile(self.archive)
        fh = zf.open(self.member)
        fh._parent_zip = zf  # keep the archive alive while the member is read
        return fh

    def __str__(self) -> str:
        return f"{self.archive.name}!{self.member}"


def ensure_extracted(raw_dir: Path, dataset_info: dict) -> Path:
    target = raw_dir / dataset_info["extract_dir"]
    if target.exists() and any(target.rglob("*.csv")):
        return target
    archive = raw_dir / dataset_info["archive"]
    if not archive.exists():
        raise FileNotFoundError(
            f"{archive} not found. Download it from {dataset_info['url']} (see README, 'Datasets')."
        )
    return archive  # read members directly from the archive


def list_csvs(source: Path) -> list:
    if source.is_file() and source.suffix == ".zip":
        with zipfile.ZipFile(source) as zf:
            members = sorted(n for n in zf.namelist() if n.lower().endswith(".csv"))
        if not members:
            raise FileNotFoundError(f"No CSV files inside {source}")
        return [ZipMember(source, m) for m in members]
    files = sorted(Path(p) for p in glob.glob(str(source / "**" / "*.csv"), recursive=True))
    if not files:
        raise FileNotFoundError(f"No CSV files under {source}")
    return files


def _open(src):
    return src.open() if isinstance(src, ZipMember) else open(src, "rb")


def _read_one_csv(path, attempted_policy: str, benign_keep: float,
                  rng: np.random.Generator, chunksize: int = 1_000_000) -> tuple[pd.DataFrame, dict]:
    with _open(path) as fh:
        header = pd.read_csv(fh, nrows=0).columns.tolist()
    mapping = normalise_columns(header)
    stats = {"file": path.name, "rows_read": 0, "dropped_attempted": 0, "thinned_benign": 0,
             "attempted_relabelled": 0}
    parts = []
    fh = _open(path)
    for chunk in pd.read_csv(fh, chunksize=chunksize, low_memory=False,
                             dtype={c: str for c in header if mapping[c] in
                                    {"src_ip", "dst_ip", "label", "timestamp", "flow_id"}}):
        chunk = chunk.rename(columns=mapping)
        stats["rows_read"] += len(chunk)
        labels = chunk["label"].astype(str).str.strip()
        table = build_label_table(labels.unique(), attempted_policy)
        cat = labels.map(table)
        attempted = labels.map({lab: is_attempted(lab) for lab in labels.unique()})
        stats["attempted_relabelled"] += int((attempted & (cat == "Benign")).sum())
        keep = cat.notna()
        stats["dropped_attempted"] += int((~keep).sum())
        if benign_keep < 1.0:
            benign = (cat == "Benign").to_numpy()
            thin = benign & (rng.random(len(chunk)) >= benign_keep)
            stats["thinned_benign"] += int(thin.sum())
            keep &= ~thin
        chunk = chunk.loc[keep.to_numpy()].copy()
        chunk["raw_label"] = labels[keep]
        chunk["category"] = cat[keep]
        chunk["attempted"] = attempted[keep].astype(bool)
        chunk = chunk.drop(columns=[c for c in ("id", "flow_id", "label", "attempted_category") if c in chunk])
        # Features -> float32 now to keep memory bounded on the big dataset.
        feat_cols = [c for c in chunk.columns if c not in NON_FEATURE_COLUMNS
                     and c not in {"raw_label", "category", "attempted"}]
        chunk[feat_cols] = chunk[feat_cols].apply(pd.to_numeric, errors="coerce").astype(np.float32)
        if "src_port" in chunk:
            chunk = chunk.drop(columns=["src_port"])
        parts.append(chunk)
    fh.close()
    return pd.concat(parts, ignore_index=True), stats


def load_flows(csv_files: list[Path], attempted_policy: str = "benign",
               benign_keep_fraction: float = 1.0, seed: int = 0) -> tuple[pd.DataFrame, list[dict]]:
    rng = np.random.default_rng(seed)
    frames, all_stats = [], []
    for f in csv_files:
        log.info("Reading %s", f.name)
        df, st = _read_one_csv(f, attempted_policy, benign_keep_fraction, rng)
        frames.append(df)
        all_stats.append(st)
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df.pop("timestamp"), format="ISO8601")
    return df, all_stats
