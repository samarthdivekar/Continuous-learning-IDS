"""Cleaning: infinities, NaNs, duplicates, chronological ordering."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.ingestion.loader import NON_FEATURE_COLUMNS

META_COLUMNS = {"ts", "src_ip", "dst_ip", "raw_label", "category", "attempted",
                "task_id", "window_id", "split", "y_multi", "y_binary", "segment_id"}


def feature_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in META_COLUMNS and c not in NON_FEATURE_COLUMNS]


def clean_flows(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return a cleaned, chronologically ordered copy plus a stats dict.

    * +-inf -> NaN -> 0. CICFlowMeter emits inf/NaN rates for zero-duration
      flows. We impute 0 instead of dropping the row because every flow is an
      edge in the graph; dropping would silently alter topology.
    * Exact duplicate records (same timestamp, endpoints and features) are
      removed; they are export artefacts, not repeated traffic.
    * Rows are sorted by timestamp with a *stable* sort, so equal timestamps
      keep file order. We never shuffle globally.
    """
    stats = {"rows_in": len(df)}
    feats = feature_columns(df)
    values = df[feats].to_numpy(dtype=np.float32, copy=True)
    inf_mask = np.isinf(values)
    stats["inf_values"] = int(inf_mask.sum())
    values[inf_mask] = np.nan
    nan_mask = np.isnan(values)
    stats["nan_values_imputed"] = int(nan_mask.sum())
    stats["rows_with_nan_or_inf"] = int(nan_mask.any(axis=1).sum())
    values[nan_mask] = 0.0
    df = df.copy()
    df[feats] = values

    before = len(df)
    # Row fingerprint instead of drop_duplicates(subset=all columns): pandas would
    # factorise every one of ~85 columns (≈6 GB of int64 for 10M rows). A 64-bit
    # hash per row is O(rows) memory; collision probability for 10^7 rows is ~3e-6.
    key = pd.util.hash_pandas_object(df[["ts", "src_ip", "dst_ip", "category", *feats]], index=False)
    df = df.loc[~key.duplicated(keep="first").to_numpy()]
    stats["duplicates_removed"] = before - len(df)

    df = df.sort_values("ts", kind="stable").reset_index(drop=True)
    stats["rows_out"] = len(df)
    return df, stats
