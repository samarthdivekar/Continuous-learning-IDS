"""Live-traffic endpoints of the public API (mounted by src/api/app.py).

    POST /sensor/pcap      a sensor uploads one capture chunk (raw pcap bytes, X-Site header)
    POST /sensor/flows     a sensor that ran the flow meter itself uploads flow records
    GET  /live/sites       every site that has reported, with its latest status
    GET  /live/windows     per-chunk timeline for one site (or all)
    GET  /live/incidents   flagged flows of the recent chunks grouped into incidents (dry-run actions)
    POST /live/label       an analyst labels flows (by id, by incident, or "everything from this site
                           in the last N minutes is normal")
    POST /live/adapt       the live model learns from labelled flows, gated against forgetting
    POST /live/reset       back to the trained model
    GET  /live/model       live model version, novelty threshold, adaptation history

Nothing here blocks traffic: incidents carry proposed rules as text, exactly as in the incident queue.
"""
from __future__ import annotations

import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, update

from src.db.models import LiveFlow, LiveWindow
from src.live.flowmeter import FlowMeterError, pcap_to_flows

router = APIRouter()

SITE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_PCAP_BYTES = 256 * 1024 * 1024
ONLINE_SECONDS = 60          # a site that has not reported for this long is shown as offline


def _app():
    from src.api import app as appmod          # late import: app.py mounts this router
    return appmod


def _ml(method: str, path: str, body: dict | None = None, params: dict | None = None):
    """Forward to the ML service, or call the in-process engine (tests / single-process runs)."""
    a = _app()
    if a.state.ml_url:
        return a._remote(method, path, json=body, params=params, timeout=600)
    svc = a.state.service
    if path == "/live/recorded_flows":
        try:
            return {"category": params["category"],
                    "flows": svc.recorded_flows(params["category"], int(params.get("n", 400)))}
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc))
    live = svc.live
    try:
        if path == "/live/score":
            return live.score(body["flows"])
        if path == "/live/adapt":
            from src.live.engine import label_id
            names = live.names
            return live.adapt([(w["flows"], [label_id(names, lab) for lab in w["labels"]]) for w in body["windows"]],
                              epochs=body.get("epochs"))
        if path == "/live/reset":
            return live.reset()
        if path == "/live/fpr_study":
            return live.fpr_study(body["flows"], teach_fraction=body.get("teach_fraction", 0.5),
                                  epochs=body.get("epochs"))
        return live.describe()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


def _site(value: str | None) -> str:
    if not value or not SITE_RE.match(value):
        raise HTTPException(422, "site must be 1-64 characters: letters, digits, '.', '_' or '-'")
    return value


def _ts(value) -> datetime | None:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso(t: datetime | None) -> str | None:
    if t is None:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()


# ------------------------------------------------------------------ ingest
class SensorFlow(BaseModel):
    ts: str | None = None
    src_ip: str
    dst_ip: str
    src_port: int | None = None
    dst_port: int | None = None
    protocol: int | None = None
    features: dict[str, float]


class SensorFlowsIn(BaseModel):
    site: str
    flows: list[SensorFlow] = Field(max_length=200_000)
    source: str = Field(default="flows", pattern="^(flows|replay|pcap)$")


def process_flows(site: str, flows: list[dict], source: str) -> dict:
    """Score one chunk of a site's flows, store it, and summarise what was found."""
    Session = _app().state.Session
    now = datetime.now(timezone.utc)
    if not flows:                              # quiet chunk: still a heartbeat for the site
        with Session() as s:
            w = LiveWindow(site=site, received_at=now, n_flows=0, n_hosts=0, n_flagged=0, n_unfamiliar=0,
                           counts={}, source=source)
            s.add(w)
            s.commit()
            return {"window_id": w.id, "site": site, "n_flows": 0, "counts": {}, "flagged": 0, "unfamiliar": 0}
    res = _ml("POST", "/live/score", {"flows": flows})
    times = [t for t in (_ts(f.get("ts")) for f in flows) if t is not None]
    flagged = sum(1 for lab in res["labels"] if lab != "Benign")
    unfamiliar = sum(res["unfamiliar"])
    with Session() as s:
        w = LiveWindow(site=site, received_at=now, window_start=min(times) if times else None,
                       window_end=max(times) if times else None, n_flows=len(flows), n_hosts=res["n_nodes"],
                       n_flagged=flagged, n_unfamiliar=unfamiliar, counts=res["counts"],
                       model_version=res["version"], source=source)
        s.add(w)
        s.flush()
        s.add_all([LiveFlow(window_id=w.id, site=site, ts=_ts(f.get("ts")), src_ip=f["src_ip"], dst_ip=f["dst_ip"],
                            src_port=f.get("src_port"), dst_port=f.get("dst_port"), protocol=f.get("protocol"),
                            features=f["features"], predicted=lab, confidence=conf, novelty=nov, unfamiliar=unf)
                   for f, lab, conf, nov, unf in zip(flows, res["labels"], res["confidence"], res["novelty"],
                                                     res["unfamiliar"])])
        s.commit()
        wid = w.id
    return {"window_id": wid, "site": site, "n_flows": len(flows), "n_hosts": res["n_nodes"],
            "counts": res["counts"], "flagged": flagged, "unfamiliar": unfamiliar, "model_version": res["version"]}


@router.post("/sensor/pcap")
async def sensor_pcap(request: Request):
    site = _site(request.headers.get("x-site"))
    body = await request.body()
    if not body:
        raise HTTPException(422, "empty capture")
    if len(body) > MAX_PCAP_BYTES:
        raise HTTPException(413, f"capture larger than {MAX_PCAP_BYTES // 2**20} MB; use shorter chunks")
    with tempfile.TemporaryDirectory(prefix="gnnids_pcap_") as tmp:
        path = Path(tmp) / "chunk.pcap"
        path.write_bytes(body)
        try:
            flows = await run_in_threadpool(pcap_to_flows, path)
        except FlowMeterError as exc:
            raise HTTPException(503, f"flow meter: {exc}")
    return await run_in_threadpool(process_flows, site, flows, "pcap")


@router.post("/sensor/flows")
def sensor_flows(body: SensorFlowsIn):
    return process_flows(_site(body.site), [f.model_dump() for f in body.flows], body.source)


class ReplayRecordedIn(BaseModel):
    category: str = Field(max_length=32)
    site: str = Field(default="sandbox")
    n: int = Field(default=5000, ge=1, le=20000)


@router.post("/sensor/replay_recorded")
def replay_recorded(body: ReplayRecordedIn):
    """Sandbox: replay REAL recorded flows of one attack category (from the dataset's held-out test
    split) into a site, as if a sensor had seen them. Nothing is generated and nothing is sent to any
    host — it is recorded traffic fed through the live scorer so a detection can be shown safely."""
    data = _ml("GET", "/live/recorded_flows", params={"category": body.category, "n": body.n})
    flows = data["flows"]
    if not flows:
        raise HTTPException(404, f"no recorded flows for category {body.category!r}")
    return {**process_flows(_site(body.site), flows, "replay"), "category": body.category,
            "replayed": len(flows)}


# ------------------------------------------------------------------ views
@router.get("/live/sites")
def live_sites():
    Session = _app().state.Session
    now = datetime.now(timezone.utc)
    recent = now - timedelta(minutes=5)
    with Session() as s:
        rows = s.execute(select(LiveWindow.site, func.max(LiveWindow.received_at), func.count(),
                                func.sum(LiveWindow.n_flows)).group_by(LiveWindow.site)).all()
        out = []
        for site, last, n_windows, n_flows in rows:
            r5 = s.execute(select(func.sum(LiveWindow.n_flows), func.sum(LiveWindow.n_flagged),
                                  func.sum(LiveWindow.n_unfamiliar))
                           .where(LiveWindow.site == site, LiveWindow.received_at >= recent)).one()
            last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            out.append({"site": site, "last_seen": _iso(last), "seconds_since": int((now - last).total_seconds()),
                        "online": (now - last).total_seconds() <= ONLINE_SECONDS, "windows": int(n_windows),
                        "flows": int(n_flows or 0), "flows_5min": int(r5[0] or 0), "flagged_5min": int(r5[1] or 0),
                        "unfamiliar_5min": int(r5[2] or 0)})
    return {"sites": sorted(out, key=lambda d: d["site"]), "online_seconds": ONLINE_SECONDS}


@router.get("/live/graph/{window_id}")
def live_graph(window_id: int, max_nodes: int = Query(150, ge=5, le=800)):
    """One live window as a host/flow graph, coloured by the model's prediction (live traffic is
    unlabelled, so there is no ground truth — edges are the predicted category, nodes that send or
    receive predicted-attack flows are marked). Same shape the Graph explorer renders."""
    with _app().state.Session() as s:
        rows = s.scalars(select(LiveFlow).where(LiveFlow.window_id == window_id).order_by(LiveFlow.id)).all()
    if not rows:
        raise HTTPException(404, f"no live window {window_id}")
    hosts = {}
    for r in rows:
        for ip in (r.src_ip, r.dst_ip):
            hosts.setdefault(ip, len(hosts))
    n = len(hosts)
    deg = np.zeros(n, int); out_deg = np.zeros(n, int); in_deg = np.zeros(n, int); atk = np.zeros(n, int)
    pairs = {}
    for r in rows:
        si, di = hosts[r.src_ip], hosts[r.dst_ip]
        out_deg[si] += 1; in_deg[di] += 1; deg[si] += 1; deg[di] += 1
        is_atk = r.predicted != "Benign"
        if is_atk:
            atk[si] += 1; atk[di] += 1
        p = pairs.setdefault((si, di), {"flows": 0, "attack_flows": 0, "unfamiliar": 0, "cats": {}})
        p["flows"] += 1
        if is_atk:
            p["attack_flows"] += 1
            p["cats"][r.predicted] = p["cats"].get(r.predicted, 0) + 1
        if r.unfamiliar:
            p["unfamiliar"] += 1
    order = sorted(range(n), key=lambda i: (atk[i] > 0, deg[i]), reverse=True)[:max_nodes]
    keep = set(order)
    ip_of = {i: ip for ip, i in hosts.items()}
    cat_counts = {}
    for r in rows:
        if r.predicted != "Benign":
            cat_counts[r.predicted] = cat_counts.get(r.predicted, 0) + 1
    edges = [{"source": si, "target": di, "flows": p["flows"], "attack_flows": p["attack_flows"],
              "unfamiliar": p["unfamiliar"], "wrong": 0,
              "category": max(p["cats"], key=p["cats"].get) if p["cats"] else "Benign"}
             for (si, di), p in pairs.items() if si in keep and di in keep]
    n_attack = int(sum(1 for r in rows if r.predicted != "Benign"))
    return {"window_id": window_id, "n_nodes": n, "n_edges": len(rows), "n_attack_edges": n_attack,
            "category_counts": cat_counts, "truncated": n > max_nodes,
            "nodes": [{"id": i, "ip": ip_of[i], "degree": int(deg[i]), "out_degree": int(out_deg[i]),
                       "in_degree": int(in_deg[i]), "attack_degree": int(atk[i])} for i in order],
            "edges": edges, "note": "Live traffic: edges are the model's predicted category, not ground truth."}


@router.get("/live/windows")
def live_windows(site: str | None = None, limit: int = Query(120, ge=1, le=2000), since_id: int = 0):
    Session = _app().state.Session
    with Session() as s:
        q = select(LiveWindow).where(LiveWindow.id > since_id)
        if site:
            q = q.where(LiveWindow.site == _site(site))
        rows = list(reversed(s.scalars(q.order_by(desc(LiveWindow.id)).limit(limit)).all()))
    return {"windows": [{"window_id": r.id, "site": r.site, "received_at": _iso(r.received_at),
                         "window_start": _iso(r.window_start), "window_end": _iso(r.window_end),
                         "n_flows": r.n_flows, "n_hosts": r.n_hosts, "flagged": r.n_flagged,
                         "unfamiliar": r.n_unfamiliar, "counts": r.counts, "model_version": r.model_version,
                         "source": r.source} for r in rows]}


def _recent_flows(s, site: str | None, windows: int):
    wq = select(LiveWindow.id)
    if site:
        wq = wq.where(LiveWindow.site == site)
    wids = s.scalars(wq.order_by(desc(LiveWindow.id)).limit(windows)).all()
    if not wids:
        return []
    return s.scalars(select(LiveFlow).where(LiveFlow.window_id.in_(wids))).all()


@router.get("/live/incidents")
def live_incidents(site: str | None = None, windows: int = Query(30, ge=1, le=500),
                   min_confidence: float = Query(0.0, ge=0.0, le=1.0)):
    from src.product.incidents import build_incidents
    from src.product.response import propose_action
    site = _site(site) if site else None
    with _app().state.Session() as s:
        rows = _recent_flows(s, site, windows)
    names = _ml("GET", "/live/model")["classes"]
    idx = {n: i for i, n in enumerate(names)}
    flagged = [r for r in rows if r.predicted != "Benign" and r.predicted in idx]
    incidents = []
    if flagged:
        probs = np.zeros((len(flagged), len(names)))
        for i, r in enumerate(flagged):
            probs[i, idx[r.predicted]] = r.confidence
            probs[i, 0] = 1.0 - r.confidence
        src = np.array([r.src_ip for r in flagged])
        dst = np.array([r.dst_ip for r in flagged])
        ts = np.array([(r.ts or datetime.now(timezone.utc)).replace(tzinfo=None) for r in flagged], dtype="datetime64[us]")
        ids = np.array([r.id for r in flagged])
        sites = np.array([r.site for r in flagged])
        for inc in build_incidents(src, dst, probs, names, threshold=min_confidence, ts=ts):
            fi = np.asarray(inc.pop("flow_indices"))
            inc["proposed"] = propose_action(inc)
            inc["proposed"]["dry_run"] = True
            inc["flow_ids"] = ids[fi][:5000].tolist()
            inc["sites"] = sorted(set(sites[fi].tolist()))
            ports = [flagged[i].dst_port for i in fi[:2000] if flagged[i].dst_port is not None]
            inc["top_ports"] = [int(p) for p, _ in sorted(((p, ports.count(p)) for p in set(ports)),
                                                          key=lambda kv: -kv[1])[:5]]
            inc["labelled"] = sum(1 for i in fi if flagged[i].analyst_label is not None)
            incidents.append(inc)
        incidents.sort(key=lambda d: -d["severity"])
    # unfamiliar traffic the model calls benign: grouped by source host, for the analyst to look at
    unf = {}
    for r in rows:
        if r.unfamiliar and r.predicted == "Benign":
            d = unf.setdefault((r.site, r.src_ip), {"site": r.site, "host": r.src_ip, "flows": 0, "flow_ids": [],
                                                     "destinations": set(), "ports": set()})
            d["flows"] += 1
            if len(d["flow_ids"]) < 5000:
                d["flow_ids"].append(r.id)
            d["destinations"].add(r.dst_ip)
            if r.dst_port is not None:
                d["ports"].add(int(r.dst_port))
    unfamiliar = sorted(({**d, "destinations": len(d["destinations"]), "ports": sorted(d["ports"])[:10]}
                         for d in unf.values()), key=lambda d: -d["flows"])[:50]
    return {"site": site, "windows": windows, "n_flows": len(rows), "flagged_flows": len(flagged),
            "incidents": incidents[:100], "unfamiliar": unfamiliar, "dry_run": True}


# ------------------------------------------------------------------ labels and learning
class LabelIn(BaseModel):
    label: str = Field(max_length=32)
    flow_ids: list[int] | None = Field(default=None, max_length=200_000)
    site: str | None = None
    last_minutes: float | None = Field(default=None, gt=0, le=240)
    only_unlabelled: bool = True


@router.post("/live/label")
def live_label(body: LabelIn):
    names = _ml("GET", "/live/model")["classes"]
    if body.label not in names:
        raise HTTPException(422, f"unknown label {body.label!r}; use one of {names}")
    if not body.flow_ids and not (body.site and body.last_minutes):
        raise HTTPException(422, "give flow_ids, or site and last_minutes")
    Session = _app().state.Session
    with Session() as s:
        q = update(LiveFlow).values(analyst_label=body.label)
        if body.flow_ids:
            q = q.where(LiveFlow.id.in_(body.flow_ids))
        else:
            since = datetime.now(timezone.utc) - timedelta(minutes=body.last_minutes)
            wids = select(LiveWindow.id).where(LiveWindow.site == _site(body.site), LiveWindow.received_at >= since)
            q = q.where(LiveFlow.window_id.in_(wids))
        if body.only_unlabelled:
            q = q.where(LiveFlow.analyst_label.is_(None))
        n = s.execute(q).rowcount
        s.commit()
    return {"labelled": int(n), "label": body.label}


class AdaptIn(BaseModel):
    site: str | None = None
    epochs: int | None = Field(default=None, ge=1, le=20)
    max_windows: int = Field(default=40, ge=1, le=200)


@router.post("/live/adapt")
def live_adapt(body: AdaptIn):
    """Learn from every labelled flow not yet learned from (newest windows first, up to max_windows)."""
    Session = _app().state.Session
    with Session() as s:
        q = select(LiveFlow.window_id).where(LiveFlow.analyst_label.is_not(None), LiveFlow.used_for_learning.is_(False))
        if body.site:
            q = q.where(LiveFlow.site == _site(body.site))
        wids = sorted(set(s.scalars(q).all()), reverse=True)[: body.max_windows]
        if not wids:
            raise HTTPException(409, "no new labelled flows; label some first (POST /live/label)")
        windows, used = [], []
        for wid in sorted(wids):
            rows = s.scalars(select(LiveFlow).where(LiveFlow.window_id == wid).order_by(LiveFlow.id)).all()
            windows.append({"flows": [{"src_ip": r.src_ip, "dst_ip": r.dst_ip, "features": r.features} for r in rows],
                            "labels": [r.analyst_label for r in rows]})
            used += [r.id for r in rows if r.analyst_label is not None]
    res = _ml("POST", "/live/adapt", {"windows": windows, "epochs": body.epochs})
    if res.get("accepted"):
        with Session() as s:
            s.execute(update(LiveFlow).where(LiveFlow.id.in_(used)).values(used_for_learning=True))
            s.commit()
    return res


class FprStudyIn(BaseModel):
    flows: list[SensorFlow] = Field(min_length=2, max_length=200_000)
    teach_fraction: float = Field(default=0.5, gt=0.0, lt=1.0)
    epochs: int | None = Field(default=None, ge=1, le=20)


@router.post("/live/fpr_study")
def live_fpr_study(body: FprStudyIn):
    """Measure false alarms on supplied benign traffic before vs after teaching (model left unchanged).
    The flows must be real benign traffic; this is how the live FPR number in docs/LIVE_DEMO.md is made."""
    return _ml("POST", "/live/fpr_study", {"flows": [f.model_dump() for f in body.flows],
                                           "teach_fraction": body.teach_fraction, "epochs": body.epochs})


@router.post("/live/reset")
def live_reset():
    """Back to the trained model. Labels are kept, but marked not yet learned, so the analyst can
    re-teach them (otherwise a reset would leave them unlearnable)."""
    res = _ml("POST", "/live/reset")
    with _app().state.Session() as s:
        n = s.execute(update(LiveFlow).where(LiveFlow.used_for_learning.is_(True))
                      .values(used_for_learning=False)).rowcount
        s.commit()
    return {**res, "labels_released": int(n)}


@router.get("/live/model")
def live_model():
    return _ml("GET", "/live/model")
