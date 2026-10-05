import numpy as np

from src.evaluation.calibration import calibration_errors, reliability


def test_perfectly_calibrated_predictions_have_zero_ece():
    # 10 flows at confidence 0.8, 8 of them correct; 10 at 1.0, all correct
    probs = np.array([[0.8, 0.2]] * 10 + [[1.0, 0.0]] * 10)
    y = np.array([0] * 8 + [1] * 2 + [0] * 10)
    e = calibration_errors(probs, y, n_bins=10)
    assert abs(e["ece"]) < 1e-12 and abs(e["mce"]) < 1e-12
    assert e["accuracy"] == 0.9


def test_overconfidence_is_measured_as_the_weighted_gap():
    # confident (0.9) and always wrong on half the flows; perfect elsewhere
    probs = np.array([[0.9, 0.1]] * 5 + [[1.0, 0.0]] * 5)
    y = np.array([1] * 5 + [0] * 5)
    e = calibration_errors(probs, y, n_bins=10)
    assert np.isclose(e["ece"], 0.5 * 0.9) and np.isclose(e["mce"], 0.9)
    # Brier: wrong flows (0.9-0)^2 + (0.1-1)^2 = 1.62, right flows 0
    assert np.isclose(e["brier"], 0.81)


def test_reliability_bins_cover_every_flow_once():
    rng = np.random.default_rng(0)
    p = rng.dirichlet(np.ones(4), size=500)
    y = rng.integers(0, 4, size=500)
    rows = reliability(p, y, n_bins=15)
    assert len(rows) == 15 and sum(r["n"] for r in rows) == 500


def test_empty_selection_is_nan_not_an_error():
    assert np.isnan(calibration_errors(np.zeros((0, 3)), np.zeros(0, dtype=int))["ece"])
