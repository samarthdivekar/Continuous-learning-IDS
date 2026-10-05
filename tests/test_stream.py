from types import SimpleNamespace

import pytest

from src.evaluation.stream import StreamRunner


class _Data:
    """Five tasks; task t's training windows have ids 100*t + i (chronological)."""
    task_categories = ["BruteForce", "DoS", "WebAttack", "Infiltration", "Botnet"]
    n_tasks = 5
    sizes = {0: 2, 1: 4, 2: 2, 3: 3, 4: 1}

    def graphs(self, t, split):
        if split != "train":
            return []
        return [SimpleNamespace(window_id=100 * t + i, task_id=t) for i in range(self.sizes[t])]


def _runner(order):
    cfg = {"drift": {"delta": 0.002, "min_windows_between": 5, "adapt_windows": 20, "stream_order": order},
           "label_mode": "multiclass", "categories": ["Benign"] + _Data.task_categories}
    return StreamRunner(cfg, _Data(), learner=None, policy="periodic")


def test_chronological_stream_is_unchanged():
    r = _runner("chronological")
    assert [g.window_id for g in r.stream_graphs()] == [100, 101, 102, 103, 200, 201, 300, 301, 302, 400]
    assert r.period_of == {}


def test_mixed_pairs_interleave_two_attacks_per_period():
    r = _runner("mixed_pairs")
    ids = [g.window_id for g in r.stream_graphs()]
    # period 1 = tasks 1 + 2 spread evenly, each in its own order; period 2 = tasks 3 + 4
    assert ids == [100, 200, 101, 102, 201, 103, 300, 301, 400, 302]   # ties go to the earlier task
    assert sorted(ids) == sorted([100, 101, 102, 103, 200, 201, 300, 301, 302, 400])   # nothing lost
    assert {r.period_of[i] for i in ids[:6]} == {1} and {r.period_of[i] for i in ids[6:]} == {2}


def test_unknown_stream_order_is_rejected():
    with pytest.raises(ValueError):
        _runner("shuffled").stream_graphs()
