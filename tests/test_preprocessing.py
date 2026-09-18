import numpy as np
import pytest

from src.graph.window_builder import SPLIT_CODES
from src.ingestion.columns import canonical_name, normalise_columns
from src.ingestion.labels import build_label_table, to_category
from src.ingestion.loader import load_flows
from src.preprocessing.clean import clean_flows, feature_columns
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.preprocessing.scaling import FeatureScaler
from tests.conftest import synthetic_raw_csv


def test_column_normalisation_handles_both_releases():
    assert canonical_name("Src IP") == "src_ip"
    assert canonical_name("Source IP") == "src_ip"
    assert canonical_name("Tot Fwd Pkts") == canonical_name("Total Fwd Packet")
    assert canonical_name("Flow Bytes/s") == "flow_bytes_per_s"
    with pytest.raises(ValueError):
        normalise_columns(["Source IP", "Src IP"])


@pytest.mark.parametrize("raw,cat", [
    ("BENIGN", "Benign"), ("FTP-Patator", "BruteForce"), ("SSH-BruteForce", "BruteForce"),
    ("DoS Hulk", "DoS"), ("Heartbleed", "DoS"), ("DDoS-LOIC-HTTP", "DDoS"), ("DDoS", "DDoS"),
    ("Web Attack - Brute Force", "WebAttack"), ("Web Attack - SQL Injection - Attempted", "WebAttack"),
    ("Infiltration - Portscan", "Infiltration"), ("Botnet Ares", "Botnet"), ("Portscan", "PortScan"),
])
def test_label_mapping(raw, cat):
    assert to_category(raw) == cat


def test_attempted_policy():
    labels = ["DoS Hulk", "DoS Hulk - Attempted", "BENIGN"]
    assert build_label_table(labels, "benign")["DoS Hulk - Attempted"] == "Benign"
    assert build_label_table(labels, "drop")["DoS Hulk - Attempted"] is None
    assert build_label_table(labels, "attack")["DoS Hulk - Attempted"] == "DoS"


def test_clean_removes_inf_nan_duplicates_and_sorts(tmp_path):
    path = tmp_path / "day.csv"
    synthetic_raw_csv(path)
    df, _ = load_flows([path], "benign")
    shuffled = df.sample(frac=1.0, random_state=0)
    clean, stats = clean_flows(shuffled)
    feats = feature_columns(clean)
    assert "src_ip" not in feats and "dst_ip" not in feats and "src_port" not in feats
    assert np.isfinite(clean[feats].to_numpy()).all()
    assert stats["duplicates_removed"] == 1
    assert stats["inf_values"] == 1
    assert clean["ts"].is_monotonic_increasing


def test_scaler_fit_on_task1_only_and_clips():
    X1 = np.abs(np.random.default_rng(0).normal(size=(100, 3))) * 10
    s = FeatureScaler(clip_value=5).fit(X1, ["a", "b", "c"])
    Z = s.transform(np.array([[1e12, 0, 0]]))
    assert Z.max() <= 5 and Z.dtype == np.float32


def test_full_pipeline_tasks_are_chronological_and_splits_consistent(cfg, tmp_path):
    raw = tmp_path / "raw.csv"
    synthetic_raw_csv(raw)
    prepare_dataset(cfg, csv_files=[raw])
    data = load_processed(cfg)
    df = data.df
    assert data.task_categories == ["BruteForce", "DoS", "PortScan"]
    # tasks are contiguous in time and ordered
    first_ts = df.groupby("task_id")["ts"].min()
    last_ts = df.groupby("task_id")["ts"].max()
    assert all(last_ts[t] <= first_ts[t + 1] for t in range(data.n_tasks - 1))
    # benign flows before the first attack belong to task 0
    assert df.loc[df["ts"].idxmin(), "task_id"] == 0
    # every window has exactly one task and one split
    assert (df.groupby("window_id")[["task_id", "split"]].nunique() == 1).all().all()
    # windows are chronological
    wstart = df.groupby("window_id")["ts"].min()
    assert wstart.is_monotonic_increasing
    # attempted flows were relabelled benign (policy default)
    assert not ((df["raw_label"].str.contains("Attempted")) & (df["category"] != "Benign")).any()
    # test split exists
    assert (df["split"] == SPLIT_CODES["test"]).any()
    # graph cache matches the table
    graphs = data.graphs(0, "train")
    assert sum(g.edge_index.shape[1] for g in graphs) == len(data.tabular(0, "train"))
