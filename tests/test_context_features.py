"""Host-context features of a hand-built 6-flow window are exactly right (experiments/run_context_baseline.py)."""
import numpy as np

from src.preprocessing.context_features import CONTEXT_NAMES, window_context


def test_six_flow_window_by_hand():
    # hosts: A=10 (a scanner), B=20, C=30, D=40
    #   f0 A->B :80   f1 A->B :443   f2 A->C :80   f3 A->D :22   f4 B->C :80   f5 C->B :80
    src = np.array([10, 10, 10, 10, 20, 30])
    dst = np.array([20, 20, 30, 40, 30, 20])
    port = np.array([80.0, 443.0, 80.0, 22.0, 80.0, 80.0])
    got = window_context(src, dst, port)
    assert got.shape == (6, 12) and len(CONTEXT_NAMES) == 12
    expect = np.array([
        # out_deg, distinct dsts, distinct ports (of src), in_deg, distinct srcs (of dst), pair flows
        [4, 3, 3, 3, 2, 2],   # f0 A->B: A sends 4 flows to B,C,D on 80/443/22; B receives f0,f1,f5 from A,C; A->B twice
        [4, 3, 3, 3, 2, 2],   # f1 A->B
        [4, 3, 3, 2, 2, 1],   # f2 A->C: C receives f2,f4 from A,B
        [4, 3, 3, 1, 1, 1],   # f3 A->D
        [1, 1, 1, 2, 2, 1],   # f4 B->C
        [1, 1, 1, 3, 2, 1],   # f5 C->B
    ], dtype=np.float32)
    np.testing.assert_array_equal(got[:, :6], expect)
    np.testing.assert_allclose(got[:, 6:], expect / 6, rtol=1e-6)


def test_empty_window_and_labels_never_used():
    assert window_context(np.array([], int), np.array([], int), np.array([])).shape == (0, 12)
