"""ADWIN drift monitor (Bifet & Gavaldà 2007) via `river`.

Monitored signal
  error       per-flow 0/1 misclassification (default). Assumes labels arrive
              with a delay, e.g. from analyst triage — standard in NIDS drift
              work and stated as an assumption in the README.
  confidence  per-flow 1 − max-softmax probability. Label-free proxy; weaker.

Granularity (`drift.granularity`)
  flow    every flow's value is fed to ADWIN (default). A window holds ~5k flows,
          so ADWIN gets enough samples to detect a change inside a handful of
          windows.
  window  one mean value per window. Kept for comparison: in the first
          experiments ADWIN never fired at this granularity, because a few
          dozen samples that swing between ~0 (benign windows) and ~1 (attack
          windows) give it too little statistical power at delta = 0.002.

Calibration
  Before the stream starts, the model's signal on held-out windows from the
  training period (task 1 validation windows) is fed to ADWIN without
  triggering anything. This establishes the "normal" error level; without it
  the very first stream windows have nothing to be compared against.

Trigger rule
  ADWIN flags a change in either direction. Only an INCREASE of the signal
  triggers adaptation; a decrease (e.g. an attack burst ending) is logged with
  triggered_retrain = False. A refractory period of `min_windows_between`
  windows stops back-to-back retrains on one burst. No flag -> no retraining.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from river import drift


@dataclass
class DriftEvent:
    stream_index: int
    window_id: int
    ts: str
    detector: str
    prev_error: float
    new_error: float
    triggered_retrain: bool
    reason: str


class ADWINMonitor:
    def __init__(self, delta: float = 0.002, min_windows_between: int = 5):
        self.delta = float(delta)
        self.min_windows_between = int(min_windows_between)
        self._new_detector()
        self.events: list[DriftEvent] = []
        self.since_last_trigger = 10 ** 9

    def _new_detector(self) -> None:
        self.detector = drift.ADWIN(delta=self.delta)

    @property
    def estimate(self) -> float:
        return float(self.detector.estimation) if self.detector.width > 0 else float("nan")

    def calibrate(self, values) -> None:
        """Feed baseline values without raising events."""
        for v in np.asarray(values, dtype=float).ravel():
            self.detector.update(float(v))

    def _decide(self, prev: float, stream_index: int, window_id: int, ts: str) -> DriftEvent:
        new = self.estimate  # after a detection ADWIN keeps only the recent sub-window
        increased = not (new <= prev)  # NaN-safe: an unknown baseline counts as an increase
        cooled = self.since_last_trigger >= self.min_windows_between
        trigger = increased and cooled
        reason = "error increased" if trigger else ("error decreased" if not increased else "refractory period")
        ev = DriftEvent(stream_index, int(window_id), str(ts), "ADWIN", prev, new, trigger, reason)
        self.events.append(ev)
        if trigger:
            self.since_last_trigger = 0
        return ev

    def update(self, value: float, stream_index: int, window_id: int, ts: str) -> DriftEvent | None:
        """One value = one window (granularity 'window')."""
        prev = self.estimate
        self.detector.update(float(value))
        self.since_last_trigger += 1
        if not self.detector.drift_detected:
            return None
        return self._decide(prev, stream_index, window_id, ts)

    def update_window(self, values, stream_index: int, window_id: int, ts: str) -> DriftEvent | None:
        """All per-flow values of one window (granularity 'flow'). At most one
        event per window; the reference level is the estimate before the window."""
        prev = self.estimate
        detected = False
        for v in np.asarray(values, dtype=float).ravel():
            self.detector.update(float(v))
            detected = detected or self.detector.drift_detected
        self.since_last_trigger += 1
        if not detected:
            return None
        return self._decide(prev, stream_index, window_id, ts)

    def notify_adapted(self) -> None:
        """Called after any adaptation (ADWIN-, schedule- or manually triggered).

        The detector is deliberately NOT reset: an empty detector has no
        baseline. The adapted model's lower error shows up as a "decrease"
        (logged, no retrain) and ADWIN drops the old sub-window itself, so the
        reference level re-bases automatically. Only the refractory period starts.
        """
        self.since_last_trigger = 0

    def events_as_dicts(self) -> list[dict]:
        from dataclasses import asdict
        return [asdict(e) for e in self.events]
