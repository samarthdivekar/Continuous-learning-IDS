"""ADWIN drift monitor (Bifet & Gavaldà 2007) via `river`.

Monitored signal
  error       per-flow 0/1 misclassification (default). Assumes labels arrive
              with a delay, e.g. from analyst triage — standard in NIDS drift
              work and stated as an assumption in the README.
  confidence  per-flow 1 − max-softmax probability. Label-free proxy; weaker.

Granularity (`drift.granularity`)
  flow    every flow's value is fed to ADWIN (default). A window holds ~5k flows,
          so ADWIN has enough samples to detect a change inside a window.
  window  one mean value per window. Kept for comparison: ADWIN never fired at
          this granularity on the real stream (a few dozen samples swinging
          between ~0 and ~1 give it too little power at delta = 0.002).

Calibration
  Before the stream starts, the model's signal on held-out windows from the
  training period (task-1 validation windows) is fed to ADWIN without raising
  events, so the first stream windows have a "normal" level to compare against.

How river 0.26.1 behaves (verified, see tests/test_drift.py)
  When `update(x)` detects a change, ADWIN drops the older sub-window W0 and
  `estimation` is the mean of the recent sub-window W1 at that moment. On the
  NEXT `update`, river RESETS the detector completely (width -> 1). So:
    * the direction of a change must be read AT the detection: compare the
      estimate just before the update (≈ mean of W0 ∪ W1, dominated by the old
      level) with the estimate just after it (mean of W1, the new level);
    * after any detection the detector starts again from the next value, i.e.
      the new level becomes the reference automatically.
  An earlier version compared the estimate before a whole 5,000-flow window
  with the estimate after it; with the reset above, an attack burst that
  started and ended inside one window could be logged as a decrease. Fixed.

Trigger rule
  A window triggers adaptation if ANY detection inside it was an increase and
  the refractory period (`min_windows_between` windows since the last
  adaptation) has passed. Decreases are logged with triggered_retrain = False.
  No flag -> no retraining.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from river import drift


@dataclass
class DriftEvent:
    stream_index: int
    window_id: int
    ts: str
    detector: str
    prev_error: float     # level before the change (estimate just before the detecting update)
    new_error: float      # level after the change (mean of ADWIN's recent sub-window at detection)
    triggered_retrain: bool
    reason: str
    n_detections: int = 1


class ADWINMonitor:
    def __init__(self, delta: float = 0.002, min_windows_between: int = 5):
        self.delta = float(delta)
        self.min_windows_between = int(min_windows_between)
        self.detector = drift.ADWIN(delta=self.delta)
        self.events: list[DriftEvent] = []
        self.since_last_trigger = 10 ** 9

    @property
    def estimate(self) -> float:
        return float(self.detector.estimation) if self.detector.width > 0 else float("nan")

    def calibrate(self, values) -> None:
        """Feed baseline values without raising events."""
        for v in np.asarray(values, dtype=float).ravel():
            self.detector.update(float(v))

    def _feed(self, values) -> list[tuple[float, float]]:
        """Update value by value; return (level_before, level_after) for every detection."""
        det = self.detector
        detections = []
        for v in np.asarray(values, dtype=float).ravel():
            before = det.estimation if det.width > 0 else float("nan")
            det.update(float(v))
            if det.drift_detected:
                detections.append((float(before), float(det.estimation)))
        return detections

    def _event(self, detections, stream_index: int, window_id: int, ts: str) -> DriftEvent | None:
        self.since_last_trigger += 1
        if not detections:
            return None
        ups = [d for d in detections if not (d[1] <= d[0])]  # NaN-safe: unknown "before" counts as an increase
        increased = bool(ups)
        prev, new = ups[0] if ups else detections[0]
        cooled = self.since_last_trigger >= self.min_windows_between
        trigger = increased and cooled
        reason = "error increased" if trigger else ("refractory period" if increased else "error decreased")
        ev = DriftEvent(stream_index, int(window_id), str(ts), "ADWIN", prev, new, trigger, reason, len(detections))
        self.events.append(ev)
        return ev

    def update(self, value: float, stream_index: int, window_id: int, ts: str) -> DriftEvent | None:
        """One value = one window (granularity 'window')."""
        return self._event(self._feed([value]), stream_index, window_id, ts)

    def update_window(self, values, stream_index: int, window_id: int, ts: str) -> DriftEvent | None:
        """All per-flow values of one window (granularity 'flow'). At most one event per window."""
        return self._event(self._feed(values), stream_index, window_id, ts)

    def notify_adapted(self) -> None:
        """Called after any adaptation (ADWIN-, schedule- or manually triggered).
        Starts the refractory period. The detector itself is not touched: river
        already restarted it after the detection that caused the adaptation, and
        for scheduled/manual adaptations the lower post-adaptation error simply
        shows up as a (logged, non-triggering) decrease."""
        self.since_last_trigger = 0

    def events_as_dicts(self) -> list[dict]:
        return [asdict(e) for e in self.events]
