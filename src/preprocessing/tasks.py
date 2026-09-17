"""Chronological partition of the flow stream into one task per attack category.

Algorithm (dataset-agnostic):
1. For every attack category, cluster its attack-flow timestamps into bursts
   (a new burst starts after a gap > `gap_seconds`). Bursts with fewer than
   `min_segment_flows` flows are ignored for *segmentation* only (their flows
   keep their labels).
2. Sort all bursts by start time and merge consecutive bursts of the same
   category -> "segments".
3. Cut the timeline at the midpoint between consecutive segments. Every flow
   (benign or attack) belongs to the segment whose time span contains it;
   benign traffic before the first attack joins the first segment.
4. task_id of a segment = rank of its category's first appearance. If a
   category re-appears later (e.g. a second day of the same attack), that
   segment is still assigned to the category's original task, so each task is
   "one attack category" as the brief requires. This is logged.

Flows of a *different* attack category that happen to fall inside a segment
keep their true label (realistic: a stray flow is still that attack).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from src.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class Segment:
    category: str
    start: pd.Timestamp
    end: pd.Timestamp
    n_attack_flows: int
    task_id: int = -1
    segment_id: int = -1


def find_segments(df: pd.DataFrame, gap_seconds: float, min_segment_flows: int) -> list[Segment]:
    bursts: list[Segment] = []
    attacks = df[df["category"] != "Benign"]
    for cat, g in attacks.groupby("category", sort=False):
        ts = g["ts"].sort_values().to_numpy()
        gaps = np.diff(ts).astype("timedelta64[us]").astype(np.int64) / 1e6
        cut = np.flatnonzero(gaps > gap_seconds) + 1
        for chunk in np.split(ts, cut):
            if len(chunk) >= min_segment_flows:
                bursts.append(Segment(cat, pd.Timestamp(chunk[0]), pd.Timestamp(chunk[-1]), len(chunk)))
    bursts.sort(key=lambda s: s.start)

    segments: list[Segment] = []
    for b in bursts:
        if segments and segments[-1].category == b.category:
            segments[-1].end = max(segments[-1].end, b.end)
            segments[-1].n_attack_flows += b.n_attack_flows
        else:
            segments.append(b)

    for a, b in zip(segments, segments[1:]):
        if b.start < a.end:
            log.warning("Segments overlap in time: %s (%s..%s) and %s (%s..%s). "
                        "Boundary placed at the midpoint; some flows cross over.",
                        a.category, a.start, a.end, b.category, b.start, b.end)

    order: dict[str, int] = {}
    for i, s in enumerate(segments):
        if s.category not in order:
            order[s.category] = len(order)
        elif segments[i - 1].category != s.category:
            log.warning("Category %s re-appears at %s; segment assigned to its original task %d",
                        s.category, s.start, order[s.category])
        s.task_id = order[s.category]
        s.segment_id = i
    return segments


def assign_tasks(df: pd.DataFrame, segments: list[Segment]) -> pd.DataFrame:
    """Add `segment_id` and `task_id` columns. `df` must be sorted by ts."""
    if not segments:
        raise ValueError("No attack segments found; cannot build a task sequence.")
    # Boundaries: midpoint between end of segment i and start of segment i+1.
    bounds = [a.end + (b.start - a.end) / 2 for a, b in zip(segments, segments[1:])]
    ts = df["ts"].to_numpy()
    seg_idx = np.searchsorted(np.array(bounds, dtype="datetime64[us]"), ts.astype("datetime64[us]"), side="right")
    df = df.copy()
    df["segment_id"] = seg_idx.astype(np.int32)
    df["task_id"] = np.array([s.task_id for s in segments], dtype=np.int16)[seg_idx]
    return df


def segments_table(segments: list[Segment]) -> pd.DataFrame:
    return pd.DataFrame([asdict(s) for s in segments])
