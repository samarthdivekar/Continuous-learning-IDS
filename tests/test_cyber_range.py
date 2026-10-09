"""The cyber range's own bookkeeping (demo/cyber_range.py), without Docker: chunks are assigned to the phase
running when they were CAPTURED, ground truth is 'the attacker is one end of the flow', and the report shows
exactly the numbers it was given."""
import importlib.util
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cyber_range", ROOT / "demo" / "cyber_range.py")
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def test_phase_is_taken_from_capture_time_not_ship_time(tmp_path):
    s = cr.Streamer("http://127.0.0.1:1", tmp_path)
    t0 = time.time()
    s.phases = [(0.0, "setup"), (t0, "normal1"), (t0 + 60, "attack1"), (t0 + 90, "teaching")]
    assert s.phase == "teaching"
    assert s.phase_at(t0 + 10) == "normal1"           # captured during normal traffic, even if shipped later
    assert s.phase_at(t0 + 61) == "attack1"
    assert s.phase_at(t0 - 5) == "setup"


def test_stats_use_the_attacker_address_as_ground_truth(tmp_path):
    s = cr.Streamer("http://127.0.0.1:1", tmp_path)
    s.records = [
        {"phase": "attack1", "id": 1, "label": "PortScan", "unsure": False, "attack": True},
        {"phase": "attack1", "id": 2, "label": "Benign", "unsure": False, "attack": True},
        {"phase": "attack1", "id": 3, "label": "DoS", "unsure": True, "attack": False},     # false alarm, abstained
        {"phase": "attack1", "id": 4, "label": "DoS", "unsure": False, "attack": False},    # false alarm, raised
        {"phase": "normal1", "id": 5, "label": "Benign", "unsure": False, "attack": False},
    ]
    st = s.stats("attack1")
    assert (st["attack_flows"], st["attack_detected"], st["attack_alarms"]) == (2, 1, 1)
    assert (st["benign_flows"], st["benign_flagged"], st["benign_alarms"]) == (2, 2, 1)
    assert st["categories"] == {"PortScan": 1} and st["attack_ids"] == [1, 2] and st["benign_ids"] == [3, 4]


def test_report_shows_the_measured_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(cr, "ROOT", tmp_path)
    ph = {"attack_flows": 0, "attack_detected": 0, "attack_alarms": 0, "benign_flows": 100, "benign_flagged": 70,
          "benign_alarms": 69, "categories": {}, "attack_ids": [], "benign_ids": []}
    att = {**ph, "attack_flows": 5000, "attack_detected": 4980, "attack_alarms": 4980, "categories": {"PortScan": 4980}}
    rep = {"phases": {"normal1": ph, "attack1": att, "normal2": {**ph, "benign_flagged": 44, "benign_alarms": 44},
                      "attack2": att},
           "adapt": {"accepted": True, "epochs_kept": 4, "epochs_max": 10, "seconds": 80,
                     "old_attacks_before": {"macro_f1": 0.975, "fpr": 0.0006},
                     "old_attacks_after": {"macro_f1": 0.972, "fpr": 0.0006},
                     "site_holdout": {"n_flows": 800, "fpr_before": 0.708, "fpr_after": 0.444}},
           "taught_attack": 5000, "taught_benign": 4000, "forget": [("DoS", 4832, 5000)],
           "latency": {"p50": 4.1, "max": 9.0}, "chunks": 120, "errors": []}
    html = cr.write_report(rep).read_text(encoding="utf-8")
    for needle in ("4980 / 5000 (99.6%)", "70 / 100 (70.0%)", "0.975", "0.972", "70.80%", "44.40%",
                   "4 of up to 10", "4832 / 5000", "accepted"):
        assert needle in html, needle
