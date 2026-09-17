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


def test_refractory_period_and_reset():
    mon = ADWINMonitor(delta=0.002, min_windows_between=500)
    mon.notify_adapted()                       # just adapted -> refractory
    events = _feed(mon, [0.01] * 100 + [0.9] * 60)   # ADWIN only checks every 32 updates
    assert events and not events[0].triggered_retrain and events[0].reason == "refractory period"
    mon.notify_adapted()
    assert mon.detector.width == 0             # fresh detector after adaptation
