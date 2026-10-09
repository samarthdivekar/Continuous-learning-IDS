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


def test_sandbox_replay_recorded_attack(client):
    # DoS exists in the synthetic fixture (DoS Hulk burst); replay real recorded flows into a site
    r = client.post("/sensor/replay_recorded", json={"category": "DoS", "site": "sandbox", "n": 50})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["category"] == "DoS" and out["replayed"] >= 1 and out["n_flows"] == out["replayed"]
    assert client.get("/live/sites").json()["sites"][0]["site"] == "sandbox"
    w = client.get("/live/windows", params={"site": "sandbox"}).json()["windows"]
    assert w and w[0]["source"] == "replay"
    assert client.post("/sensor/replay_recorded", json={"category": "NoSuchAttack"}).status_code == 404


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
    r = client.post("/live/label", json={"label": "Benign", "site": "home", "last_minutes": 5, "include_suspicious": True})
    assert r.status_code == 200 and r.json()["labelled"] == 40
    res = client.post("/live/adapt", json={"epochs": 1}).json()
    assert {"accepted", "old_attacks_before", "old_attacks_after", "labelled_flows"} <= set(res)
    assert res["labelled_flows"] == 32 and res["site_holdout"]["n_flows"] == 8   # every 5th normal flow held back
    model = client.get("/live/model").json()
    if res["accepted"]:
        assert model["version"] == 1
        assert client.post("/live/adapt", json={}).status_code == 409            # each label is learned once
    else:
        assert model["version"] == 0 and "rolled back" in res["reason"]
    assert client.post("/live/reset").json()["reset"] is True


def test_chunks_are_scored_in_site_context_and_non_ip_is_dropped(client):
    first = client.post("/sensor/flows", json={"site": "lab", "flows": _flows(client, 30)}).json()
    assert first["n_context"] == 0
    nxt = _flows(client, 10) + [{**_flows(client, 1)[0], "protocol": 0, "src_ip": "8.6.0.1", "dst_ip": "8.0.6.4"}]
    r = client.post("/sensor/flows", json={"site": "lab", "flows": nxt, "source": "pcap", "detail": True}).json()
    assert r["n_context"] == 30 and r["n_flows"] == 10 and r["ignored_non_ip"] == 1   # ARP-like record dropped
    assert len(r["flow_ids"]) == len(r["labels"]) == 10
    other = client.post("/sensor/flows", json={"site": "elsewhere", "flows": _flows(client, 5)}).json()
    assert other["n_context"] == 0                                    # context never crosses sites
    g = client.get("/live/site_graph", params={"site": "lab"}).json()
    assert g["n_edges"] == 40 and g["nodes"]


def test_live_incidents_are_per_site(client, monkeypatch):
    # force every flow to be flagged so the grouping itself is what is tested
    real = client.svc.live.score

    def all_dos(flows, context=None):
        out = real(flows, context)
        out["labels"] = ["DoS"] * len(flows)
        out["confidence"] = [0.99] * len(flows)
        return out
    monkeypatch.setattr(client.svc.live, "score", all_dos)
    for site in ("site-a", "site-b"):                  # the same private addresses at two sites
        client.post("/sensor/flows", json={"site": site, "flows": _flows(client, 20)})
    inc = client.get("/live/incidents").json()["incidents"]
    assert inc and all(len(i["sites"]) == 1 for i in inc)
    assert {i["site"] for i in inc} == {"site-a", "site-b"}
    assert client.get("/live/incidents", params={"minutes": 0.001}).status_code == 200


def test_learning_survives_a_restart_and_reset_deletes_it(client):
    from src.live.engine import LiveEngine
    live = client.svc.live
    live.max_drop = 1.0                                   # force acceptance: this test is about persistence
    client.post("/sensor/flows", json={"site": "home", "flows": _flows(client, 40)})
    client.post("/live/label", json={"label": "Benign", "site": "home", "last_minutes": 5, "include_suspicious": True})
    res = client.post("/live/adapt", json={"epochs": 1}).json()
    assert res["accepted"] and res["saved"] and live.state_path.exists()
    weights = {k: v.clone() for k, v in live.learner.model.state_dict().items()}

    fresh = LiveEngine(client.svc)                        # what a restarted service builds
    d = fresh.describe()
    assert d["restored_from_disk"] and d["version"] == res["version"] and d["learned_windows"] == 1
    for k, v in fresh.learner.model.state_dict().items():
        assert (v.cpu() == weights[k].cpu()).all()

    r = client.post("/live/reset").json()
    assert r["reset"] and r["labels_released"] == 40 and not live.state_path.exists()
    assert client.post("/live/adapt", json={"epochs": 1}).status_code == 200   # labels can be re-taught


def test_gate_rolls_back_on_false_alarms_and_holds_out_site_traffic(client):
    live = client.svc.live
    client.post("/sensor/flows", json={"site": "home", "flows": _flows(client, 50)})
    client.post("/live/label", json={"label": "Benign", "site": "home", "last_minutes": 5, "include_suspicious": True})
    live.max_drop, live.max_fpr_rise = 1.0, -1.0          # any FPR change at all now fails the gate
    v = live.version
    res = client.post("/live/adapt", json={"epochs": 1}).json()
    assert not res["accepted"] and "false alarms" in res["reason"] and live.version == v
    assert res["site_holdout"]["n_flows"] == 10            # every 5th of 50 normal flows held back, not trained on
    assert not live.state_path.exists()                    # a rolled-back update is never saved


def test_bulk_normal_skips_suspicious_flows_and_labels_can_be_undone(client, monkeypatch):
    real = client.svc.live.score

    def half_flagged(flows, context=None):
        out = real(flows, context)
        out["labels"] = ["DoS" if i % 2 else "Benign" for i in range(len(flows))]
        out["unfamiliar"] = [False] * len(flows)
        return out
    monkeypatch.setattr(client.svc.live, "score", half_flagged)
    out = client.post("/sensor/flows", json={"site": "home", "flows": _flows(client, 20), "detail": True}).json()
    r = client.post("/live/label", json={"label": "Benign", "site": "home", "last_minutes": 5, "analyst": "sam"}).json()
    assert r["labelled"] == 10 and r["skipped_suspicious"] == 10       # the flagged half is left for review
    with client.Session() as s:
        rows = s.query(LiveFlow).filter(LiveFlow.analyst_label.isnot(None)).all()
        assert {x.labelled_by for x in rows} == {"sam"} and all(x.labelled_at for x in rows)
    assert client.post("/live/unlabel", json={"flow_ids": out["flow_ids"]}).json()["unlabelled"] == 10


def test_old_database_gets_new_columns(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE live_flows (id INTEGER PRIMARY KEY, window_id INTEGER, site VARCHAR(64), "
                "src_ip VARCHAR(64), dst_ip VARCHAR(64), features JSON, predicted VARCHAR(32), confidence FLOAT, "
                "unfamiliar BOOLEAN, used_for_learning BOOLEAN)")
    con.execute("INSERT INTO live_flows (id, site, src_ip, dst_ip, predicted) VALUES (1, 's', 'a', 'b', 'Benign')")
    con.commit()
    con.close()
    reset_for_tests(f"sqlite:///{db.as_posix()}")
    cols = {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(live_flows)")}
    assert {"labelled_by", "labelled_at", "ts", "analyst_label"} <= cols
    assert sqlite3.connect(db).execute("SELECT count(*) FROM live_flows").fetchone()[0] == 1   # data kept


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
