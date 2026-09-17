"""ADWIN drift monitor (Bifet & Gavaldà 2007) via `river`.

Monitored signal, one value per incoming window:
  error       fraction of flows misclassified (default). Assumes labels arrive
              with a delay, e.g. from analyst triage — standard in NIDS drift
              literature, and stated as an assumption in the README.
  confidence  1 − mean max-softmax probability. Label-free proxy; weaker, but
              usable when no labels are available.

Trigger rule
  ADWIN flags a change in either direction. Only an INCREASE of the monitored
  signal triggers adaptation; a decrease (e.g. an attack burst ending) is
  logged with triggered_retrain = False. A refractory period
  (`min_windows_between`) stops back-to-back retrains on one burst.
  No flag -> no retraining. Avoiding unnecessary retraining is an objective.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

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
        return float(self.detector.estimation)

    def update(self, value: float, stream_index: int, window_id: int, ts: str) -> DriftEvent | None:
        prev = self.estimate if self.detector.width > 0 else float("nan")
        self.detector.update(float(value))
        self.since_last_trigger += 1
        if not self.detector.drift_detected:
            return None
        new = self.estimate  # after a detection ADWIN keeps only the recent sub-window
        increased = not (new <= prev)  # NaN-safe: treat unknown prev as an increase
        cooled = self.since_last_trigger >= self.min_windows_between
        trigger = increased and cooled
        reason = "error increased" if trigger else ("error decreased" if not increased else "refractory period")
        ev = DriftEvent(stream_index, int(window_id), str(ts), "ADWIN", prev, new, trigger, reason)
        self.events.append(ev)
        return ev

    def notify_adapted(self) -> None:
        """The model changed, so its error distribution changed: restart ADWIN."""
        self._new_detector()
        self.since_last_trigger = 0

    def events_as_dicts(self) -> list[dict]:
        return [asdict(e) for e in self.events]
