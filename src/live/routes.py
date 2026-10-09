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

import os
import re
import tempfile
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import defer

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
            return live.score(body["flows"], body.get("context"))
        if path == "/live/adapt":
            from src.live.engine import label_id
            names = live.names
            return live.adapt([(w["flows"], [label_id(names, lab) for lab in w["labels"]]) for w in body["windows"]],
                              epochs=body.get("epochs"), holdout=body.get("holdout"))
        if path == "/live/reset":
            return live.reset()
        if path == "/live/explain":
            return live.explain(body["flows"], body["edge"])
        if path == "/live/fpr_study":
            return live.fpr_study(body["flows"], teach_fraction=body.get("teach_fraction", 0.5),
                                  epochs=body.get("epochs"))
        return live.describe()
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


def _chunks(ids: list, size: int = 500):
    """SQLite caps the variables in one statement; large id lists go in slices."""
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


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
    detail: bool = False          # also return each flow's id and predicted label (cyber range, tests)


RETENTION_DAYS = float(os.environ.get("GNNIDS_LIVE_RETENTION_DAYS", "7"))
_ingests = 0


def purge_older_than(days: float) -> dict:
    """Delete live flows older than `days` (they are personal data in clear text). Flows an analyst
    labelled are kept as the record of what the model was taught; windows left empty go too."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with _app().state.Session() as s:
        old = select(LiveWindow.id).where(LiveWindow.received_at < since)
        n_flows = s.execute(LiveFlow.__table__.delete().where(LiveFlow.window_id.in_(old),
                                                              LiveFlow.analyst_label.is_(None))).rowcount
        still = select(LiveFlow.window_id).distinct()
        n_windows = s.execute(LiveWindow.__table__.delete().where(LiveWindow.received_at < since,
                                                                  LiveWindow.id.not_in(still))).rowcount
        s.commit()
    return {"deleted_flows": int(n_flows), "deleted_windows": int(n_windows), "older_than_days": days}


CONTEXT_SECONDS = 120        # a chunk is scored inside the site's flows of the last two minutes ...
CONTEXT_MAX_FLOWS = 5000     # ... up to the training window size (5,000 flows per graph)


# Each site's recent flows, kept in memory: reading 5,000 flows' features back from SQLite for every chunk
# made ingest fall behind real time under load (cyber range: 47-100 s behind). Rebuilt from the database
# after a restart.
_RECENT: dict[str, "deque[tuple[float, dict]]"] = {}
_RECENT_LOCK = threading.Lock()


def _remember(site: str, flows: list[dict], now: datetime) -> None:
    with _RECENT_LOCK:
        dq = _RECENT.setdefault(site, deque(maxlen=CONTEXT_MAX_FLOWS))
        t = now.timestamp()
        dq.extend((t, {"src_ip": f["src_ip"], "dst_ip": f["dst_ip"], "features": f["features"]}) for f in flows)


def _context(site: str, n_new: int, now: datetime) -> list[dict]:
    """The site's most recent earlier flows, so a few-second chunk is not scored as a tiny graph."""
    room = CONTEXT_MAX_FLOWS - n_new
    if room <= 0:
        return []
    since = now - timedelta(seconds=CONTEXT_SECONDS)
    with _RECENT_LOCK:
        dq = _RECENT.get(site)
        if dq is not None:
            cutoff = since.timestamp()
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            return [f for _, f in list(dq)[-room:]]
    with _app().state.Session() as s:              # first chunk since a restart: rebuild from the database
        wids = select(LiveWindow.id).where(LiveWindow.site == site, LiveWindow.received_at >= since)
        rows = s.execute(select(LiveFlow.src_ip, LiveFlow.dst_ip, LiveFlow.features)
                         .where(LiveFlow.window_id.in_(wids)).order_by(desc(LiveFlow.id)).limit(room)).all()
    flows = [{"src_ip": a, "dst_ip": b, "features": f} for a, b, f in reversed(rows)]
    _remember(site, flows, now)
    return flows


def process_flows(site: str, flows: list[dict], source: str, detail: bool = False) -> dict:
    """Score one chunk of a site's flows, store it, and summarise what was found."""
    from src.live.flowmeter import is_ip_flow
    global _ingests
    _ingests += 1
    if _ingests % 500 == 1 and RETENTION_DAYS > 0:       # cheap, occasional retention sweep
        purge_older_than(RETENTION_DAYS)
    Session = _app().state.Session
    now = datetime.now(timezone.utc)
    n_in = len(flows)
    flows = [f for f in flows if is_ip_flow(f)] if source == "pcap" else flows
    ignored = n_in - len(flows)
    if not flows:                              # quiet chunk: still a heartbeat for the site
        with Session() as s:
            w = LiveWindow(site=site, received_at=now, n_flows=0, n_hosts=0, n_flagged=0, n_unfamiliar=0,
                           counts={}, source=source)
            s.add(w)
            s.commit()
            return {"window_id": w.id, "site": site, "n_flows": 0, "counts": {}, "flagged": 0, "unfamiliar": 0,
                    "ignored_non_ip": ignored, **({"flow_ids": [], "labels": []} if detail else {})}
    if source == "replay":
        # recorded traffic replayed now: it happens now (its 2017 capture times would date the incident in 2017)
        flows = [{**f, "ts": now.isoformat()} for f in flows]
    context = _context(site, len(flows), now) if source != "replay" else []
    res = _ml("POST", "/live/score", {"flows": flows, "context": context})
    times = [t for t in (_ts(f.get("ts")) for f in flows) if t is not None]
    unsure = res.get("unsure") or [False] * len(flows)
    cat_unc = res.get("category_uncertain") or [False] * len(flows)
    # an alarm is a CONFIDENT attack verdict; when the model abstains the flow goes to an analyst instead
    flagged = sum(1 for lab, u in zip(res["labels"], unsure) if lab != "Benign" and not u)
    unfamiliar = sum(res["unfamiliar"])
    with Session() as s:
        w = LiveWindow(site=site, received_at=now, window_start=min(times) if times else None,
                       window_end=max(times) if times else None, n_flows=len(flows), n_hosts=res["n_nodes"],
                       n_flagged=flagged, n_unfamiliar=unfamiliar, n_unsure=int(sum(unsure)), counts=res["counts"],
                       model_version=res["version"], source=source)
        s.add(w)
        s.flush()
        rows = [LiveFlow(window_id=w.id, site=site, ts=_ts(f.get("ts")), src_ip=f["src_ip"], dst_ip=f["dst_ip"],
                         src_port=f.get("src_port"), dst_port=f.get("dst_port"), protocol=f.get("protocol"),
                         features=f["features"], predicted=lab, confidence=conf, novelty=nov, unfamiliar=unf,
                         unsure=bool(u), category_uncertain=bool(cu))
                for f, lab, conf, nov, unf, u, cu in zip(flows, res["labels"], res["confidence"], res["novelty"],
                                                         res["unfamiliar"], unsure, cat_unc)]
        s.add_all(rows)
        s.commit()
        wid = w.id
        ids = [r.id for r in rows] if detail else None
    if source != "replay":
        _remember(site, flows, now)
    out = {"window_id": wid, "site": site, "n_flows": len(flows), "n_hosts": res["n_nodes"],
           "n_context": res.get("n_context", 0), "counts": res["counts"], "flagged": flagged,
           "unfamiliar": unfamiliar, "unsure": int(sum(unsure)), "model_version": res["version"],
           "ignored_non_ip": ignored}
    if detail:
        out["flow_ids"], out["labels"], out["unsure_flags"] = ids, res["labels"], [bool(u) for u in unsure]
    return out


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
    return process_flows(_site(body.site), [f.model_dump() for f in body.flows], body.source, body.detail)


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
                                  func.sum(LiveWindow.n_unfamiliar), func.sum(LiveWindow.n_unsure))
                           .where(LiveWindow.site == site, LiveWindow.received_at >= recent)).one()
            last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
            out.append({"site": site, "last_seen": _iso(last), "seconds_since": int((now - last).total_seconds()),
                        "online": (now - last).total_seconds() <= ONLINE_SECONDS, "windows": int(n_windows),
                        "flows": int(n_flows or 0), "flows_5min": int(r5[0] or 0), "flagged_5min": int(r5[1] or 0),
                        "unfamiliar_5min": int(r5[2] or 0), "unsure_5min": int(r5[3] or 0)})
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
    return {"window_id": window_id, **_graph_payload(rows, max_nodes)}


@router.get("/live/site_graph")
def live_site_graph(site: str, seconds: int = Query(120, ge=5, le=3600), max_nodes: int = Query(150, ge=5, le=800)):
    """A site's traffic of the last `seconds` as one graph: the same span the live scorer looks at
    (each chunk is scored inside the site's recent flows), rather than one few-second chunk."""
    site = _site(site)
    since = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    with _app().state.Session() as s:
        wids = select(LiveWindow.id).where(LiveWindow.site == site, LiveWindow.received_at >= since)
        rows = s.scalars(select(LiveFlow).where(LiveFlow.window_id.in_(wids))
                         .order_by(desc(LiveFlow.id)).limit(CONTEXT_MAX_FLOWS)).all()
    return {"site": site, "seconds": seconds, **_graph_payload(rows, max_nodes)}


def _graph_payload(rows, max_nodes: int) -> dict:
    if not rows:
        return {"n_nodes": 0, "n_edges": 0, "n_attack_edges": 0, "category_counts": {}, "truncated": False,
                "nodes": [], "edges": [], "note": "no traffic in this span"}
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
    return {"n_nodes": n, "n_edges": len(rows), "n_attack_edges": n_attack,
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


def _recent_flows(s, site: str | None, windows: int, minutes: float | None = None):
    wq = select(LiveWindow.id)
    if site:
        wq = wq.where(LiveWindow.site == site)
    if minutes:
        wq = wq.where(LiveWindow.received_at >= datetime.now(timezone.utc) - timedelta(minutes=minutes))
    wids = s.scalars(wq.order_by(desc(LiveWindow.id)).limit(windows)).all()
    if not wids:
        return []
    # the incident views never read the 83-feature JSON; not loading it keeps a 3-second poll cheap
    return s.scalars(select(LiveFlow).options(defer(LiveFlow.features)).where(LiveFlow.window_id.in_(wids))).all()


@router.get("/live/incidents")
def live_incidents(site: str | None = None, windows: int = Query(30, ge=1, le=500),
                   minutes: float = Query(15, gt=0, le=1440),
                   min_confidence: float = Query(0.0, ge=0.0, le=1.0)):
    """Incidents of the last `minutes` only (an old incident must not look current), grouped PER SITE:
    two sites can both use 192.168.1.x, and those are different machines."""
    from src.product.incidents import build_incidents
    from src.product.response import propose_action
    site = _site(site) if site else None
    with _app().state.Session() as s:
        rows = _recent_flows(s, site, windows, minutes)
    names = _ml("GET", "/live/model")["classes"]
    idx = {n: i for i, n in enumerate(names)}
    # incidents are built from confident attack verdicts only; abstentions are listed separately below
    flagged = [r for r in rows if r.predicted != "Benign" and r.predicted in idx and not r.unsure]
    incidents = []
    by_site: dict[str, list] = {}
    for r in flagged:
        by_site.setdefault(r.site, []).append(r)
    now = datetime.now(timezone.utc)
    for site_name, fl in by_site.items():
        probs = np.zeros((len(fl), len(names)))
        for i, r in enumerate(fl):
            probs[i, idx[r.predicted]] = r.confidence
            probs[i, 0] = 1.0 - r.confidence
        src = np.array([r.src_ip for r in fl])
        dst = np.array([r.dst_ip for r in fl])
        ts = np.array([(r.ts or now).replace(tzinfo=None) for r in fl], dtype="datetime64[us]")
        ids = np.array([r.id for r in fl])
        for inc in build_incidents(src, dst, probs, names, threshold=min_confidence, ts=ts):
            fi = np.asarray(inc.pop("flow_indices"))
            inc["site"] = site_name
            inc["sites"] = [site_name]
            inc["proposed"] = propose_action(inc)
            inc["proposed"]["dry_run"] = True
            inc["flow_ids"] = ids[fi][:5000].tolist()
            ports = [fl[i].dst_port for i in fi[:2000] if fl[i].dst_port is not None]
            inc["top_ports"] = [int(p) for p, _ in sorted(((p, ports.count(p)) for p in set(ports)),
                                                          key=lambda kv: -kv[1])[:5]]
            inc["labelled"] = sum(1 for i in fi if fl[i].analyst_label is not None)
            # share of the incident's flows where the model was sure it is an attack but not of which kind
            inc["category_uncertain_share"] = float(np.mean([bool(fl[i].category_uncertain) for i in fi]))
            incidents.append(inc)
    incidents.sort(key=lambda d: -d["severity"])
    for k, inc in enumerate(incidents):
        inc["incident_id"] = k + 1                     # rank in this view (kept for compatibility)
    _attach_records(incidents)
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
    # the model abstained (conformal set was not one class): no alarm, an analyst decides
    uns = {}
    for r in rows:
        if r.unsure and r.analyst_label is None:
            d = uns.setdefault((r.site, r.src_ip), {"site": r.site, "host": r.src_ip, "flows": 0, "flow_ids": [],
                                                     "leaning": {}})
            d["flows"] += 1
            if len(d["flow_ids"]) < 5000:
                d["flow_ids"].append(r.id)
            d["leaning"][r.predicted] = d["leaning"].get(r.predicted, 0) + 1
    unsure = sorted(uns.values(), key=lambda d: -d["flows"])[:50]
    return {"site": site, "windows": windows, "minutes": minutes, "n_flows": len(rows), "flagged_flows": len(flagged),
            "incidents": incidents[:100], "unfamiliar": unfamiliar, "unsure": unsure, "dry_run": True}


def _attach_records(incidents: list[dict]) -> None:
    """Give every grouped incident its stored record (created on first sight), keyed by site, category and
    key host, and update when it was last active. A closed incident with activity after it was closed is
    marked 'reopened'."""
    from src.db.models import LiveIncident
    if not incidents:
        return
    now = datetime.now(timezone.utc)
    with _app().state.Session() as s:
        for inc in incidents:
            rec = s.scalars(select(LiveIncident).where(LiveIncident.site == inc["site"],
                                                       LiveIncident.category == inc["category"],
                                                       LiveIncident.key_host == inc["key_host"])).first()
            end = _ts(inc.get("end")) or now
            if rec is None:
                rec = LiveIncident(site=inc["site"], category=inc["category"], key_host=inc["key_host"],
                                   first_seen=_ts(inc.get("start")) or now, last_seen=end, max_flows=inc["n_flows"])
                s.add(rec)
            else:
                last = rec.last_seen if rec.last_seen.tzinfo else rec.last_seen.replace(tzinfo=timezone.utc)
                if end > last:
                    rec.last_seen = end
                    closed_at = rec.status_at.replace(tzinfo=timezone.utc) if rec.status_at and not rec.status_at.tzinfo \
                        else rec.status_at
                    if rec.status == "closed" and closed_at and end > closed_at:
                        rec.status = "reopened"
                rec.max_flows = max(rec.max_flows or 0, inc["n_flows"])
            s.flush()
            inc["record"] = _incident_dict(rec)
        s.commit()


def _incident_dict(r) -> dict:
    return {"id": r.id, "site": r.site, "category": r.category, "key_host": r.key_host,
            "first_seen": _iso(r.first_seen), "last_seen": _iso(r.last_seen), "max_flows": r.max_flows,
            "status": r.status, "status_at": _iso(r.status_at), "status_by": r.status_by, "note": r.note}


class IncidentStatusIn(BaseModel):
    status: str = Field(pattern="^(open|acknowledged|closed)$")
    analyst: str = Field(default="analyst", max_length=64)
    note: str | None = Field(default=None, max_length=1000)


@router.post("/live/incident_records/{record_id}/status")
def live_incident_status(record_id: int, body: IncidentStatusIn):
    """Acknowledge, close or reopen a live incident record (who and when are kept)."""
    from src.db.models import LiveIncident
    with _app().state.Session() as s:
        r = s.get(LiveIncident, record_id)
        if r is None:
            raise HTTPException(404, f"no incident record {record_id}")
        r.status, r.status_at, r.status_by = body.status, datetime.now(timezone.utc), body.analyst
        if body.note is not None:
            r.note = body.note
        s.commit()
        return _incident_dict(r)


@router.get("/live/incident_records")
def live_incident_records(site: str | None = None, status: str | None = None, limit: int = Query(200, ge=1, le=2000)):
    """Every live incident ever seen (newest activity first), with its lifecycle status."""
    from src.db.models import LiveIncident
    with _app().state.Session() as s:
        q = select(LiveIncident)
        if site:
            q = q.where(LiveIncident.site == _site(site))
        if status:
            q = q.where(LiveIncident.status == status)
        return {"records": [_incident_dict(r) for r in s.scalars(q.order_by(desc(LiveIncident.last_seen)).limit(limit))]}


@router.get("/live/explain/{flow_id}")
def live_explain(flow_id: int):
    """Why the live model flagged (or passed) one live flow, rebuilt in the context it was scored in: its
    chunk plus the site's preceding flows (up to 5,000), as in process_flows."""
    with _app().state.Session() as s:
        f = s.get(LiveFlow, flow_id)
        if f is None:
            raise HTTPException(404, f"no live flow {flow_id}")
        w = s.get(LiveWindow, f.window_id)
        chunk = s.execute(select(LiveFlow.id, LiveFlow.src_ip, LiveFlow.dst_ip, LiveFlow.features)
                          .where(LiveFlow.window_id == f.window_id).order_by(LiveFlow.id)).all()
        received = w.received_at if w.received_at.tzinfo else w.received_at.replace(tzinfo=timezone.utc)
        ctx_w = select(LiveWindow.id).where(LiveWindow.site == f.site, LiveWindow.id < f.window_id,
                                            LiveWindow.received_at >= received - timedelta(seconds=CONTEXT_SECONDS))
        room = max(0, CONTEXT_MAX_FLOWS - len(chunk))
        ctx = s.execute(select(LiveFlow.src_ip, LiveFlow.dst_ip, LiveFlow.features).where(LiveFlow.window_id.in_(ctx_w))
                        .order_by(desc(LiveFlow.id)).limit(room)).all() if room else []
        site, predicted, stored_conf = f.site, f.predicted, f.confidence
    flows = [{"src_ip": a, "dst_ip": b, "features": x} for a, b, x in reversed(ctx)]
    edge = len(flows) + [r.id for r in chunk].index(flow_id)
    flows += [{"src_ip": r.src_ip, "dst_ip": r.dst_ip, "features": r.features} for r in chunk]
    out = _ml("POST", "/live/explain", {"flows": flows, "edge": edge})
    return {**out, "flow_id": flow_id, "site": site, "predicted_when_scored": predicted,
            "confidence_when_scored": stored_conf, "context_flows": len(ctx)}


@router.get("/live/incidents/cef", response_class=PlainTextResponse)
def live_incidents_cef(site: str | None = None, minutes: float = Query(15, gt=0, le=1440)):
    """The live incidents as ArcSight CEF lines for a SIEM. Text only: nothing is sent anywhere."""
    from src.product.siem import incidents_to_cef
    data = live_incidents(site=site, windows=500, minutes=minutes, min_confidence=0.0)
    lines = [incidents_to_cef([i], f"live-{i['site']}", "gnn_ewc_replay-live") for i in data["incidents"]]
    name = f"live_incidents_{site or 'all'}.cef"
    return PlainTextResponse("\n".join(lines), headers={"Content-Disposition": f'attachment; filename="{name}"'})


class LiveActionIn(BaseModel):
    site: str
    category: str = Field(max_length=32)
    target: str = Field(max_length=64)
    minutes: float = Field(default=15, gt=0, le=1440)


@router.post("/live/actions")
def live_propose(body: LiveActionIn):
    """Record the proposed (dry-run) action of a live incident, so it can be approved or rejected through
    POST /actions/{id}/decision like the recorded-data queue. The incident is re-derived on the server and
    must still exist with that category and target."""
    from src.db.models import ResponseAction
    site = _site(body.site)
    inc = live_incidents(site=site, windows=500, minutes=body.minutes, min_confidence=0.0)["incidents"]
    match = next((i for i in inc if i["category"] == body.category and i["proposed"]["target"] == body.target), None)
    if match is None:
        raise HTTPException(409, "incident no longer present; reload the live view")
    pr = match["proposed"]
    with _app().state.Session() as s:
        existing = s.scalars(select(ResponseAction).where(
            ResponseAction.site == site, ResponseAction.category == match["category"],
            ResponseAction.target == pr["target"], ResponseAction.action == pr["action"],
            ResponseAction.status == "proposed")).first()
        if existing is None:
            existing = ResponseAction(window_id=-1, incident_id=match["incident_id"], model_name="gnn_ewc_replay-live",
                                      category=match["category"], action=pr["action"], target=pr["target"],
                                      rationale=pr["rationale"], rule_linux=pr["rules"].get("linux"),
                                      rule_windows=pr["rules"].get("windows"), status="proposed", site=site)
            s.add(existing)
            s.commit()
        return _app()._action_dict(existing)


# ------------------------------------------------------------------ labels and learning
class LabelIn(BaseModel):
    label: str = Field(max_length=32)
    flow_ids: list[int] | None = Field(default=None, max_length=200_000)
    site: str | None = None
    last_minutes: float | None = Field(default=None, gt=0, le=240)
    only_unlabelled: bool = True
    # Bulk "everything from this site was normal" must not whitelist an attack that happened in that
    # period: by default it skips flows the model flagged or found unfamiliar (label those one by one).
    include_suspicious: bool = False
    analyst: str = Field(default="analyst", max_length=64)


@router.post("/live/label")
def live_label(body: LabelIn):
    names = _ml("GET", "/live/model")["classes"]
    if body.label not in names:
        raise HTTPException(422, f"unknown label {body.label!r}; use one of {names}")
    if not body.flow_ids and not (body.site and body.last_minutes):
        raise HTTPException(422, "give flow_ids, or site and last_minutes")
    Session = _app().state.Session
    skipped = 0
    with Session() as s:
        q = update(LiveFlow).values(analyst_label=body.label, labelled_by=body.analyst,
                                    labelled_at=datetime.now(timezone.utc))
        if body.only_unlabelled:
            q = q.where(LiveFlow.analyst_label.is_(None))
        if body.flow_ids:                         # in chunks: one huge IN (...) exceeds SQLite's variable limit
            n = sum(s.execute(q.where(LiveFlow.id.in_(part))).rowcount for part in _chunks(body.flow_ids))
            s.commit()
            return {"labelled": int(n), "label": body.label, "skipped_suspicious": 0}
        since = datetime.now(timezone.utc) - timedelta(minutes=body.last_minutes)
        wids = select(LiveWindow.id).where(LiveWindow.site == _site(body.site), LiveWindow.received_at >= since)
        q = q.where(LiveFlow.window_id.in_(wids))
        if body.label == "Benign" and not body.include_suspicious:
            suspicious = (LiveFlow.predicted != "Benign") | LiveFlow.unfamiliar.is_(True) | LiveFlow.unsure.is_(True)
            cnt = select(func.count()).select_from(LiveFlow).where(LiveFlow.window_id.in_(wids), suspicious)
            if body.only_unlabelled:
                cnt = cnt.where(LiveFlow.analyst_label.is_(None))
            skipped = int(s.scalar(cnt) or 0)
            q = q.where(LiveFlow.predicted == "Benign", LiveFlow.unfamiliar.is_not(True), LiveFlow.unsure.is_not(True))
        n = s.execute(q).rowcount
        s.commit()
    return {"labelled": int(n), "label": body.label, "skipped_suspicious": skipped}


class UnlabelIn(BaseModel):
    flow_ids: list[int] = Field(min_length=1, max_length=200_000)


@router.post("/live/unlabel")
def live_unlabel(body: UnlabelIn):
    """Undo labels the model has not learned from yet (learned ones need /live/reset)."""
    with _app().state.Session() as s:
        n = sum(s.execute(update(LiveFlow).where(LiveFlow.id.in_(part), LiveFlow.used_for_learning.is_(False),
                                                 LiveFlow.analyst_label.is_not(None))
                          .values(analyst_label=None, labelled_by=None, labelled_at=None)).rowcount
                for part in _chunks(body.flow_ids))
        s.commit()
    return {"unlabelled": int(n)}


DRIFT_MIN_LABELS = 50        # below this many labelled flows the disagreement rate is not reported as drift
DRIFT_THRESHOLD = 0.10       # model disagrees with analysts on >10 % of not-yet-learned labels -> adapt recommended


@router.get("/live/drift")
def live_drift(minutes: float = Query(60, gt=0, le=10080)):
    """Live drift signal. Live traffic has no ground truth except analyst labels, so the signal is the
    model's error on the flows analysts labelled (as the drift experiment's ADWIN watches the labelled
    error, README §4): per site, how often the label differs from what the model said, over labels not yet
    learned from. A high rate means the traffic has moved away from what the model knows."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    with _app().state.Session() as s:
        rows = s.execute(select(LiveFlow.site, LiveFlow.analyst_label, LiveFlow.predicted)
                         .where(LiveFlow.analyst_label.is_not(None), LiveFlow.used_for_learning.is_(False),
                                LiveFlow.labelled_at >= since)).all()
    per: dict[str, dict] = {}
    for site, lab, pred in rows:
        d = per.setdefault(site, {"site": site, "labelled": 0, "disagree": 0, "by_label": {}})
        d["labelled"] += 1
        wrong = lab != pred
        d["disagree"] += int(wrong)
        b = d["by_label"].setdefault(lab, {"labelled": 0, "model_disagreed": 0})
        b["labelled"] += 1
        b["model_disagreed"] += int(wrong)
    for d in per.values():
        d["error_rate"] = d["disagree"] / d["labelled"]
        d["enough_labels"] = d["labelled"] >= DRIFT_MIN_LABELS
        d["adapt_recommended"] = d["enough_labels"] and d["error_rate"] > DRIFT_THRESHOLD
    return {"minutes": minutes, "min_labels": DRIFT_MIN_LABELS, "threshold": DRIFT_THRESHOLD,
            "sites": sorted(per.values(), key=lambda d: d["site"])}


HOLDOUT_EVERY = 5            # every 5th flow an analyst marked normal is held back to measure false alarms
MIN_GROUP_FLOWS = 1000       # a training graph smaller than this is folded into its neighbour


def _training_groups(rows) -> list[list]:
    """The labelled live traffic as training graphs shaped like the training data (cyber range, 2026-10-09):
      * per site, consecutive capture chunks merged up to 5,000 flows — training on few-second chunk graphs
        made the model forget (old-attack macro-F1 0.975 -> 0.642; merged: 0.974);
      * a normal-only period and a period containing an attack are kept in separate graphs — merged together,
        the scanned servers turned the normal flows next to them 'attack-like' (site false alarms 49 % after
        teaching; kept apart: 3 %);
      * but a group under 1,000 flows joins its neighbour, since a tiny graph again caused forgetting."""
    by_site: dict[str, dict[int, list]] = {}
    for r in rows:
        by_site.setdefault(r.site, {}).setdefault(r.window_id, []).append(r)
    out = []
    for chunks in by_site.values():
        groups: list[tuple[str, list]] = []
        for wid in sorted(chunks):
            fl = chunks[wid]
            kind = "attack" if any(r.analyst_label not in (None, "Benign") for r in fl) else "normal"
            if groups and groups[-1][0] == kind and len(groups[-1][1]) + len(fl) <= CONTEXT_MAX_FLOWS:
                groups[-1][1].extend(fl)
            else:
                groups.append((kind, list(fl)))
        merged: list[list] = []
        for _, fl in groups:
            if merged and (len(fl) < MIN_GROUP_FLOWS or len(merged[-1]) < MIN_GROUP_FLOWS) \
                    and len(merged[-1]) + len(fl) <= CONTEXT_MAX_FLOWS:
                merged[-1].extend(fl)
            else:
                merged.append(list(fl))
        out += merged
    return out


class AdaptIn(BaseModel):
    site: str | None = None
    epochs: int | None = Field(default=None, ge=1, le=20)
    max_windows: int = Field(default=200, ge=1, le=500)      # capture chunks to draw labels from (newest first)


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
        rows = s.scalars(select(LiveFlow).where(LiveFlow.window_id.in_(wids))
                         .order_by(LiveFlow.site, LiveFlow.id)).all()
        windows, used, holdout = [], [], []
        n_benign = 0
        for part in _training_groups(rows):
            labels, hold = [], []
            for j, r in enumerate(part):
                lab = r.analyst_label
                if lab == "Benign":
                    n_benign += 1
                    if n_benign % HOLDOUT_EVERY == 0:          # held back: stays in the graph unlabelled, measured only
                        hold.append(j)
                        lab = None
                labels.append(lab)
            windows.append({"flows": [{"src_ip": r.src_ip, "dst_ip": r.dst_ip, "features": r.features}
                                      for r in part], "labels": labels})
            holdout.append(hold)
            used += [r.id for r in part if r.analyst_label is not None]
    res = _ml("POST", "/live/adapt", {"windows": windows, "epochs": body.epochs, "holdout": holdout})
    if res.get("accepted"):
        # by window, not by flow id: thousands of ids in one IN (...) exceed SQLite's variable limit
        with Session() as s:
            s.execute(update(LiveFlow).where(LiveFlow.window_id.in_(wids), LiveFlow.analyst_label.is_not(None),
                                             LiveFlow.used_for_learning.is_(False)).values(used_for_learning=True))
            s.commit()
    res["marked_learned"] = len(used)
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


class PurgeIn(BaseModel):
    older_than_days: float = Field(default=RETENTION_DAYS, ge=0)


@router.post("/live/purge")
def live_purge(body: PurgeIn):
    """Delete unlabelled live flows older than N days now (0 = all unlabelled live flows)."""
    return purge_older_than(body.older_than_days)


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
