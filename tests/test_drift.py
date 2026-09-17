from src.drift.adwin_monitor import ADWINMonitor


def _feed(mon, values, start=0):
    events = []
    for i, v in enumerate(values, start):
        ev = mon.update(v, i, i, f"t{i}")
        if ev:
            events.append(ev)
    return events


def test_no_drift_on_stationary_signal():
    mon = ADWINMonitor(delta=0.002, min_windows_between=1)
    assert _feed(mon, [0.01] * 300) == []


def test_error_increase_triggers_retrain():
    mon = ADWINMonitor(delta=0.002, min_windows_between=1)
    events = _feed(mon, [0.01] * 100 + [0.6] * 30)
    assert events and events[0].triggered_retrain
    assert events[0].new_error > events[0].prev_error
    assert events[0].stream_index >= 100


def test_error_decrease_is_logged_but_does_not_retrain():
    mon = ADWINMonitor(delta=0.002, min_windows_between=1)
    events = _feed(mon, [0.6] * 100 + [0.01] * 40)
    assert events and not any(e.triggered_retrain for e in events)
    assert events[0].reason == "error decreased"


def test_refractory_period_keeps_baseline():
    mon = ADWINMonitor(delta=0.002, min_windows_between=500)
    mon.notify_adapted()                       # just adapted -> refractory
    events = _feed(mon, [0.01] * 100 + [0.9] * 60)   # ADWIN only checks every 32 updates
    assert events and not events[0].triggered_retrain and events[0].reason == "refractory period"
    width = mon.detector.width
    mon.notify_adapted()
    assert mon.detector.width == width and width > 0   # baseline is not thrown away


def test_flow_granularity_detects_within_few_windows_after_calibration():
    import numpy as np
    rng = np.random.default_rng(0)
    mon = ADWINMonitor(delta=0.002, min_windows_between=1)
    mon.calibrate(rng.random(20_000) < 0.002)          # held-out baseline: 0.2 % error
    for k in range(3):                                  # normal windows: no event
        assert mon.update_window(rng.random(5000) < 0.002, k, k, "") is None
    ev = None
    for k in range(3, 6):                               # novel attack: 30 % of flows misclassified
        ev = ev or mon.update_window(rng.random(5000) < 0.3, k, k, "")
    assert ev is not None and ev.triggered_retrain and ev.stream_index == 3


def test_window_granularity_lacks_power_without_baseline():
    """Documents the failure mode seen in the first live run: few, noisy
    per-window values starting mid-attack give ADWIN nothing to detect."""
    import numpy as np
    rng = np.random.default_rng(1)
    mon = ADWINMonitor(delta=0.002, min_windows_between=1)
    values = np.where(rng.random(70) < 0.35, rng.uniform(0.5, 1.0, 70), rng.uniform(0, 0.01, 70))
    assert _feed(mon, values) == []
