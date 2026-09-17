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


def test_burst_inside_one_window_is_an_increase():
    """Reviewer's counter-example for the old window-level direction check: a
    1,000-flow misclassified burst followed by clean traffic inside ONE window
    used to be logged as 'error decreased'. river resets ADWIN after each
    detection, so direction must be decided per detection."""
    import numpy as np
    rng = np.random.default_rng(0)
    mon = ADWINMonitor(delta=0.002, min_windows_between=1)
    mon.calibrate(rng.random(70_000) < 0.02)
    window = np.r_[np.ones(1000), (rng.random(4000) < 0.01).astype(float)]
    ev = mon.update_window(window, 0, 0, "")
    assert ev is not None and ev.triggered_retrain and ev.reason == "error increased"
    assert ev.new_error > ev.prev_error


def test_river_resets_after_detection():
    """Pins the river behaviour the monitor relies on."""
    from river import drift
    a = drift.ADWIN(delta=0.002)
    for _ in range(2000):
        a.update(0.0)
    for _ in range(200):
        before = a.estimation
        a.update(1.0)
        if a.drift_detected:
            break
    # at detection the kept recent sub-window is clearly above the old level
    # (it can still contain a few pre-change values, so it need not exceed 0.5)
    assert a.drift_detected and a.estimation > before + 0.1
    a.update(1.0)
    assert a.width == 1   # full reset on the next update
