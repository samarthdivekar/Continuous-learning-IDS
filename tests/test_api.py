"""API endpoint tests against a temporary SQLite database and a tiny synthetic
dataset (test fixture only; nothing here reaches results/)."""
import time

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.service import MLService
from src.db.models import Metric, Prediction
from src.db.session import reset_for_tests
from src.evaluation.continual import run_task_sequence
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides
from tests.conftest import synthetic_raw_csv


@pytest.fixture
def client(cfg, tmp_path):
    raw = tmp_path / "raw.csv"
    synthetic_raw_csv(raw)
    cfg = apply_overrides(cfg, [f"paths.checkpoints={tmp_path / 'ckpt'}"])
    prepare_dataset(cfg, csv_files=[raw])
    data = load_processed(cfg)
    ckpt = tmp_path / "ckpt" / cfg["dataset"] / cfg["label_mode"]
    run_task_sequence(cfg, data, ["xgboost_static", "gnn_ewc_replay", "gnn_naive", "ffnn_ewc_replay"],
                      tmp_path / "res", checkpoint_dir=ckpt)
    url = f"sqlite:///{(tmp_path / 'api.db').as_posix()}"
    Session = reset_for_tests(url)
    svc = MLService(cfg, session_factory=Session)
    svc.load_models()
    app = create_app(database_url=url, service=svc)
    with TestClient(app) as c:
        c.svc = svc
        c.Session = Session
        c.data = data
        yield c


def _flow(i, src="10.0.0.1", dst="10.0.0.2"):
    return {"ts": f"2017-07-04T12:00:{i % 60:02d}", "src_ip": src, "dst_ip": dst,
            "features": {"Flow Duration": 100.0 + i, "Total Fwd Packet": 3, "Dst Port": 80}, "label": "BENIGN"}


def test_health(client):
    r = client.get("/health").json()
    assert r["status"] == "ok" and r["database"] is True
    assert set(r["ml"]["models_loaded"]) == {"xgboost_static", "gnn_ewc_replay", "gnn_naive", "ffnn_ewc_replay"}
    assert client.get("/api/health").status_code == 200


def test_ingest_then_predict_by_flow_ids(client):
    r = client.post("/ingest", json={"flows": [_flow(i) for i in range(5)]})
    assert r.status_code == 200 and r.json()["ingested"] == 5
    ids = r.json()["flow_ids"]
    p = client.post("/predict", json={"flow_ids": ids})
    assert p.status_code == 200
    body = p.json()
    assert body["n_flows"] == 5 and body["n_nodes"] == 2
    for m in ("gnn_ewc_replay", "xgboost_static"):
        assert len(body["models"][m]["labels"]) == 5
        assert all(0 <= c <= 1 for c in body["models"][m]["confidence"])
    assert any("imputed" in w for w in body["warnings"])  # most features absent in this request
    with client.Session() as s:  # one stored prediction per flow per model
        assert s.query(Prediction).filter(Prediction.flow_id.in_(ids)).count() == 5 * len(body["models"])


def test_predict_window_and_validation(client):
    wid = int(client.data.graphs(0, "test")[0].window_id)
    body = client.post("/predict", json={"window_id": wid, "models": ["gnn_naive"]}).json()
    assert list(body["models"]) == ["gnn_naive"] and "true_counts" in body
    assert client.post("/predict", json={}).status_code == 422
    assert client.post("/predict", json={"window_id": 999999}).status_code == 404
    assert client.post("/ingest", json={"flows": []}).status_code == 422


def test_graph_endpoint(client):
    wid = int(client.data.graphs(0, "train")[0].window_id)
    g = client.get(f"/graph/{wid}?max_nodes=10").json()
    assert g["window_id"] == wid and g["n_edges"] > 0
    assert len(g["nodes"]) <= 10
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert client.get("/graph/424242").status_code == 404


def test_metrics_and_drift_status_empty_then_seeded(client):
    assert client.get("/metrics").json()["series"] == {}
    with client.Session() as s:
        s.add(Metric(run_id="t", source="continual", model_name="gnn_ewc_replay", task_id=0, accuracy=0.9,
                     macro_f1=0.8, retention_rate=1.0, fpr=0.01))
        s.commit()
    m = client.get("/metrics?source=continual").json()
    assert m["series"]["gnn_ewc_replay"][0]["accuracy"] == 0.9
    assert client.get("/metrics?source=bogus").status_code == 422
    d = client.get("/drift-status").json()
    assert d["events"] == [] and d["demo"] == {"status": "idle"}


def test_retrain_without_demo_is_rejected(client):
    r = client.post("/retrain").json()
    assert r["accepted"] is False


def test_live_demo_writes_windows_events_and_metrics(client):
    r = client.post("/demo/start", json={"delay_seconds": 0.0, "eval_every": 2})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert client.post("/demo/start", json={}).status_code in (200, 409)
    for _ in range(600):
        st = client.get("/demo/status").json()
        if st["status"] in ("finished", "failed"):
            break
        if st["status"] == "streaming" and st["position"] >= 1:
            client.post("/retrain")
        time.sleep(0.1)
    assert st["status"] == "finished", st
    w = client.get(f"/stream/windows?run_id={run_id}").json()["windows"]
    assert len(w) > 0 and {x["model_name"] for x in w} >= {"gnn_ewc_replay", "xgboost_static"}
    m = client.get(f"/metrics?source=stream&run_id={run_id}").json()
    assert "gnn_ewc_replay" in m["series"]
    d = client.get(f"/drift-status?run_id={run_id}").json()
    assert d["demo"]["status"] == "finished"
