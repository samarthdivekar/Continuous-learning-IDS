"""Live traffic path (src/live): flow-meter header check, sensor ingest, incidents, labels and gated
adaptation, against a temporary SQLite database and the tiny synthetic dataset (test fixture only)."""
import csv

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.api.service import MLService
from src.db.models import LiveFlow
from src.db.session import reset_for_tests
from src.evaluation.continual import run_task_sequence
from src.live import flowmeter
from src.live.flowmeter import EXPECTED_HEADER, FlowMeterError, check_header, read_flow_csv
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides
from tests.conftest import synthetic_raw_csv


# ------------------------------------------------------------------ flow meter
def test_header_must_match_training_data():
    check_header(list(EXPECTED_HEADER))
    with pytest.raises(FlowMeterError, match="missing"):
        check_header([c for c in EXPECTED_HEADER if c != "ICMP Type"])
    with pytest.raises(FlowMeterError, match="unexpected"):
        check_header(EXPECTED_HEADER[:-1] + ["Total Connection Flow Time", "Label"])
    swapped = list(EXPECTED_HEADER)
    swapped[7], swapped[8] = swapped[8], swapped[7]
    with pytest.raises(FlowMeterError, match="different order"):
        check_header(swapped)


def test_read_flow_csv(tmp_path):
    row = {c: "1" for c in EXPECTED_HEADER}
    row.update({"Flow ID": "a", "Src IP": "192.168.1.5", "Dst IP": "192.168.1.9", "Src Port": "51000",
                "Dst Port": "80", "Protocol": "6", "Timestamp": "2026-10-08 01:02:03.000004",
                "Flow Bytes/s": "NaN", "Label": "NeedManualLabel"})
    p = tmp_path / "f.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(EXPECTED_HEADER)
        w.writerow([row[c] for c in EXPECTED_HEADER])
        w.writerow(["truncated", "line"])                     # interrupted write: skipped
    flows = read_flow_csv(p)
    assert len(flows) == 1
    f = flows[0]
    assert (f["src_ip"], f["dst_ip"], f["dst_port"], f["protocol"]) == ("192.168.1.5", "192.168.1.9", 80, 6)
    assert f["ts"] == "2026-10-08T01:02:03.000004+00:00"
    assert "Src IP" not in f["features"] and "Label" not in f["features"]
    assert f["features"]["Dst Port"] == 80.0 and f["features"]["ICMP Code"] == 1.0
    assert f["features"]["Flow Bytes/s"] == 0.0                # NaN -> 0, as in training


# ------------------------------------------------------------------ API
@pytest.fixture
def client(cfg, tmp_path):
    raw = tmp_path / "raw.csv"
    synthetic_raw_csv(raw)
    cfg = apply_overrides(cfg, [f"paths.checkpoints={tmp_path / 'ckpt'}"])
    prepare_dataset(cfg, csv_files=[raw])
    data = load_processed(cfg)
    ckpt = tmp_path / "ckpt" / cfg["dataset"] / cfg["label_mode"]
    run_task_sequence(cfg, data, ["xgboost_static", "gnn_ewc_replay", "gnn_naive", "ffnn_ewc_replay"], tmp_path / "res", checkpoint_dir=ckpt)
    url = f"sqlite:///{(tmp_path / 'live.db').as_posix()}"
    Session = reset_for_tests(url)
    svc = MLService(cfg, session_factory=Session)
    svc.load_models()
    with TestClient(create_app(database_url=url, service=svc)) as c:
        c.svc, c.Session = svc, Session
        yield c


def _flows(client, n, src="192.168.1.5", dst="192.168.1.9"):
    return [{"ts": f"2026-10-08T01:00:{i % 60:02d}+00:00", "src_ip": src, "dst_ip": f"{dst[:-1]}{i % 5}",
             "src_port": 50000 + i, "dst_port": 443, "protocol": 6,
             "features": {c: float(i % 7 + 1) for c in client.svc.scaler.columns}} for i in range(n)]


def test_sensor_flows_are_scored_and_stored(client):
    r = client.post("/sensor/flows", json={"site": "home-lan", "flows": _flows(client, 30)})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_flows"] == 30 and sum(out["counts"].values()) == 30 and out["model_version"] == 0
    with client.Session() as s:
        assert s.query(LiveFlow).filter_by(window_id=out["window_id"]).count() == 30
    sites = client.get("/live/sites").json()["sites"]
    assert [x["site"] for x in sites] == ["home-lan"] and sites[0]["online"] and sites[0]["flows"] == 30
    w = client.get("/live/windows", params={"site": "home-lan"}).json()["windows"]
    assert len(w) == 1 and w[0]["n_flows"] == 30
    inc = client.get("/live/incidents", params={"site": "home-lan"}).json()
    assert inc["dry_run"] is True and inc["n_flows"] == 30
    for i in inc["incidents"]:
        assert i["proposed"]["dry_run"] is True and i["flow_ids"]


def test_live_graph(client):
    out = client.post("/sensor/flows", json={"site": "home", "flows": _flows(client, 20)}).json()
    g = client.get(f"/live/graph/{out['window_id']}").json()
    assert g["n_edges"] == 20 and g["nodes"] and g["edges"]
    assert all({"id", "ip", "degree", "attack_degree"} <= set(n) for n in g["nodes"])
    assert all({"source", "target", "flows", "category"} <= set(e) for e in g["edges"])
    ids = {n["id"] for n in g["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in g["edges"])
    assert client.get("/live/graph/999999").status_code == 404


def test_empty_chunk_is_a_heartbeat(client):
    r = client.post("/sensor/flows", json={"site": "office", "flows": []})
    assert r.status_code == 200 and r.json()["n_flows"] == 0
    assert client.get("/live/sites").json()["sites"][0]["online"]


def test_sensor_input_is_validated(client):
    assert client.post("/sensor/flows", json={"site": "bad site!", "flows": []}).status_code == 422
    partial = _flows(client, 3)
    for f in partial:
        f["features"] = {"Flow Duration": 1.0}
    r = client.post("/sensor/flows", json={"site": "home", "flows": partial})
    assert r.status_code == 422 and "not imputed" in r.json()["detail"]
    assert client.post("/sensor/pcap", content=b"x").status_code == 422          # no X-Site header


def test_pcap_upload_reports_a_missing_flow_meter(client, monkeypatch):
    def unavailable(path, timeout=300):
        raise FlowMeterError("Docker Desktop is not running")
    monkeypatch.setattr("src.live.routes.pcap_to_flows", unavailable)
    r = client.post("/sensor/pcap", content=b"\xd4\xc3\xb2\xa1", headers={"X-Site": "home"})
    assert r.status_code == 503 and "Docker" in r.json()["detail"]


def test_label_then_adapt_is_gated_and_learns_once(client):
    client.post("/sensor/flows", json={"site": "home", "flows": _flows(client, 40)})
    assert client.post("/live/label", json={"label": "NotAClass", "site": "home", "last_minutes": 5}).status_code == 422
    assert client.post("/live/adapt", json={}).status_code == 409                # nothing labelled yet
    r = client.post("/live/label", json={"label": "Benign", "site": "home", "last_minutes": 5})
    assert r.status_code == 200 and r.json()["labelled"] == 40
    res = client.post("/live/adapt", json={"epochs": 1}).json()
    assert {"accepted", "old_attacks_before", "old_attacks_after", "labelled_flows"} <= set(res)
    assert res["labelled_flows"] == 40
    model = client.get("/live/model").json()
    if res["accepted"]:
        assert model["version"] == 1
        assert client.post("/live/adapt", json={}).status_code == 409            # each label is learned once
    else:
        assert model["version"] == 0 and "rolled back" in res["reason"]
    assert client.post("/live/reset").json()["reset"] is True


def test_fpr_study_measures_and_restores(client):
    before = client.get("/live/model").json()["version"]
    flows = _flows(client, 20)
    r = client.post("/live/fpr_study", json={"flows": flows, "teach_fraction": 0.5, "epochs": 1})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["n_teach"] == 10 and out["n_holdout"] == 10 and out["model_unchanged"] is True
    assert 0.0 <= out["fpr_before"] <= 1.0 and 0.0 <= out["fpr_after"] <= 1.0
    assert {"old_attack_f1_before", "old_attack_f1_after"} <= set(out)
    assert client.get("/live/model").json()["version"] == before      # the study changed nothing
    assert client.post("/live/fpr_study", json={"flows": flows[:1]}).status_code == 422


def test_flow_meter_reports_missing_docker(monkeypatch):
    monkeypatch.setattr(flowmeter.shutil, "which", lambda name: None)
    with pytest.raises(FlowMeterError, match="not installed"):
        flowmeter.pcap_to_flows("nothing.pcap")
