"""Host-statistics features of experiments/run_context_baseline.py on a hand-built window."""
import numpy as np

from src.preprocessing.context_features import CONTEXT_FEATURES, N_CONTEXT_FEATURES, window_context


def test_six_flow_window_is_exactly_right():
    # host 0 scans hosts 1, 2, 3 on ports 22, 80, 443; host 4 sends two flows to host 1 on port 80;
    # host 1 answers host 0 once on port 5000
    src = np.array([0, 0, 0, 4, 4, 1])
    dst = np.array([1, 2, 3, 1, 1, 0])
    port = np.array([22, 80, 443, 80, 80, 5000])
    got = window_context(src, dst, port)
    assert got.shape == (6, N_CONTEXT_FEATURES) == (6, 12)
    expected_counts = {
        "src_out_degree":      [3, 3, 3, 2, 2, 1],
        "src_distinct_dst":    [3, 3, 3, 1, 1, 1],
        "src_distinct_dports": [3, 3, 3, 1, 1, 1],
        "dst_in_degree":       [3, 1, 1, 3, 3, 1],   # host 1 receives 1 (from 0) + 2 (from 4)
        "dst_distinct_src":    [2, 1, 1, 2, 2, 1],
        "pair_flows":          [1, 1, 1, 2, 2, 1],   # (0,1) and (1,0) are different pairs
    }
    for name, want in expected_counts.items():
        col = CONTEXT_FEATURES.index(name)
        assert got[:, col].tolist() == want, name
        frac = CONTEXT_FEATURES.index(f"{name}_frac")
        assert np.array_equal(got[:, frac], np.array(want) / 6), name


def test_port_values_only_need_to_be_equal_when_ports_are_equal():
    # scaled (standardised) port values must give the same counts as raw ports
    src, dst = np.array([0, 0, 0]), np.array([1, 1, 2])
    raw = window_context(src, dst, np.array([80, 443, 80]))
    scaled = window_context(src, dst, (np.array([80, 443, 80]) - 3000.0) / 9000.0)
    assert np.array_equal(raw, scaled)


def test_empty_window():
    assert window_context(np.array([]), np.array([]), np.array([])).shape == (0, 12)
