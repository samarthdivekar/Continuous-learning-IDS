"""Host-context baseline and feature ablation (review points 3 and 5)."""
import json
from pathlib import Path

import numpy as np
import torch

from src.graph.host_context import CONTEXT_NAMES, N_CONTEXT, PORT_INDEX, host_context
from src.ingestion.columns import canonical_name


def test_counts_are_what_they_say():
    # host 0 scans hosts 1-3 on ports 10, 20, 30; host 4 sends two flows to host 1 on port 80
    ei = torch.tensor([[0, 0, 0, 4, 4], [1, 2, 3, 1, 1]])
    ports = np.array([10, 20, 30, 80, 80], dtype=float)
    raw = np.expm1(host_context(ei, ports) * np.log1p(5)).round().astype(int)
    col = {n: raw[:, i] for i, n in enumerate(CONTEXT_NAMES)}
    assert col["src_flows_out"].tolist() == [3, 3, 3, 2, 2]
    assert col["src_distinct_dst"].tolist() == [3, 3, 3, 1, 1]
    assert col["src_distinct_dst_ports"].tolist() == [3, 3, 3, 1, 1]
    assert col["dst_flows_in"].tolist() == [3, 1, 1, 3, 3]            # host 1 receives 1 + 2 flows
    assert col["dst_distinct_src"].tolist() == [2, 1, 1, 2, 2]
    assert col["dst_distinct_ports_hit"].tolist() == [2, 1, 1, 2, 2]   # host 1 is hit on ports 10 and 80
    assert col["pair_flows"].tolist() == [1, 1, 1, 2, 2]
    assert raw.shape == (5, N_CONTEXT)


def test_dst_port_is_the_first_feature_of_every_processed_dataset():
    metas = list(Path("data/processed").glob("*/meta.json"))
    for m in metas:                                      # only checkable where data was prepared
        cols = json.loads(m.read_text(encoding="utf-8"))["feature_columns"]
        assert canonical_name(cols[PORT_INDEX]) == "dst_port", m


def test_ctx_learners_train_and_predict(cfg, tmp_path):
    from src.evaluation.continual import run_task_sequence
    from src.preprocessing.pipeline import load_processed, prepare_dataset
    from tests.conftest import synthetic_raw_csv
    raw = tmp_path / "raw.csv"
    synthetic_raw_csv(raw)
    prepare_dataset(cfg, csv_files=[raw])
    data = load_processed(cfg)
    res = run_task_sequence(cfg, data, ["ffnn_ctx_ewc_replay", "xgboost_replay", "xgboost_joint", "xgboost_ctx_replay"],
                            tmp_path / "res")
    assert res is not None


def test_feature_drop_blanks_the_named_columns(cfg, tmp_path):
    from src.preprocessing.pipeline import load_processed, prepare_dataset
    from src.utils.config import apply_overrides
    from tests.conftest import synthetic_raw_csv
    raw = tmp_path / "raw.csv"
    synthetic_raw_csv(raw)
    prepare_dataset(cfg, csv_files=[raw])
    cols = load_processed(cfg).feature_columns
    drop = [c for c in ("dst_port", "protocol", "fwd_init_win_bytes", "bwd_init_win_bytes") if c in cols]
    data = load_processed(apply_overrides(cfg, [f"features.drop={drop}"]))
    g = data.graphs(0, "train")[0]
    idx = [cols.index(c) for c in drop]
    assert drop and float(g.edge_attr[:, idx].abs().sum()) == 0.0
    assert float(g.edge_attr.abs().sum()) > 0                         # everything else untouched
