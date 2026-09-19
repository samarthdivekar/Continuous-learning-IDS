"""Public REST API (brief §8, layer 4).

    uvicorn src.api.app:app --port 8000

Every endpoint is served both at the root (/health, /predict, ...) and under
/api (used by the dashboard, and by the nginx container's reverse proxy).

ML-heavy work (/predict, /retrain, /graph, /demo/*) is delegated to MLService.
In docker-compose that service runs in its own container (src/api/ml_app.py)
and this app forwards those calls to ML_SERVICE_URL; locally it runs in-process.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import case, desc, func, select, text

from src.db.models import DriftEventRow, FlowRecord, GraphWindow, Metric, Prediction, ResponseAction, WindowStat
from src.db.session import get_sessionmaker
from src.utils.config import REPO_ROOT


# ------------------------------------------------------------------ schemas
class FlowIn(BaseModel):
    ts: datetime
    src_ip: str
    dst_ip: str
    features: dict[str, float] = Field(description="raw CICFlowMeter features, original or canonical names")
    label: str | None = None


class IngestIn(BaseModel):
    flows: list[FlowIn] = Field(min_length=1, max_length=100_000)
    window_id: int | None = None
    task_id: int | None = None
    split: str | None = None


class PredictIn(BaseModel):
    flows: list[FlowIn] | None = None
    flow_ids: list[int] | None = Field(default=None, description="classify previously ingested flows")
    window_id: int | None = Field(default=None, description="classify a cached window graph")
    models: list[str] | None = None
    store: bool = True


class ProposeIn(BaseModel):
    window_id: int
    incident_id: int
    model: str = "gnn_ewc_replay"


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    analyst: str = Field(default="analyst", max_length=64)
    note: str | None = Field(default=None, max_length=1000)


class DemoStartIn(BaseModel):
    delay_seconds: float = 0.5
    eval_every: int = 10
    max_windows: int | None = None


# ------------------------------------------------------------------ app state
class State:
    Session = None
    service = None          # in-process MLService, or None when remote
    ml_url: str | None = None


state = State()


def _remote(method: str, path: str, **kw):
    try:
        r = httpx.request(method, f"{state.ml_url}{path}", timeout=120, **kw)
    except httpx.HTTPError as exc:
        raise HTTPException(503, f"ML service unreachable: {exc}")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.json().get("detail", r.text))
    return r.json()


def series_key(model: str, policy: str | None) -> str:
    """Dashboard series id. Each model's DEFAULT deployment keeps the bare model name
    (ADWIN for adaptive models, 'never' for the static baseline); every other
    policy of the drift experiment (periodic, oracle, never-for-an-adaptive-model)
    gets its own 'model:policy' series so different runs are never merged."""
    default = "never" if model == "xgboost_static" else "adwin"
    return model if policy in (None, default) else f"{model}:{policy}"


def _action_dict(r) -> dict:
    return {"id": r.id, "created_at": r.created_at.isoformat() if r.created_at else None, "window_id": r.window_id,
            "incident_id": r.incident_id, "model": r.model_name, "category": r.category, "action": r.action,
            "target": r.target, "rationale": r.rationale, "rule_linux": r.rule_linux, "rule_windows": r.rule_windows,
            "status": r.status, "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "decided_by": r.decided_by, "note": r.note, "dry_run": True}


def store_predictions(Session, flow_ids: list[int], result: dict) -> int:
    now = datetime.now(timezone.utc)
    rows = [Prediction(flow_id=fid, model_name=model, predicted_label=lab, confidence=conf, ts=now)
            for model, r in result.get("models", {}).items()
            for fid, lab, conf in zip(flow_ids, r["labels"], r["confidence"])]
    with Session() as s:
        s.add_all(rows)
        s.commit()
    return len(rows)


def create_app(database_url: str | None = None, service=None, load_models: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        state.Session = get_sessionmaker(database_url)
        state.ml_url = os.environ.get("ML_SERVICE_URL") or None
        if state.ml_url:
            state.service = None
        elif service is not None:
            state.service = service
        else:
            from src.api.service import MLService
            state.service = MLService(session_factory=state.Session)
            if load_models:
                state.service.load_models()
        yield
        if state.service is not None:
            state.service.stop_demo()

    app = FastAPI(title="Continual-learning GNN-IDS", version="1.0", lifespan=lifespan)
    router = APIRouter()

    @router.get("/health")
    def health():
        db_ok = True
        try:
            with state.Session() as s:
                s.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        if state.ml_url:
            try:
                ml = _remote("GET", "/health")
            except HTTPException as exc:
                ml = {"status": "unreachable", "detail": exc.detail}
        else:
            svc = state.service
            ml = {"status": "in-process", "dataset": svc.cfg["dataset"], "label_mode": svc.cfg["label_mode"],
                  "data_available": svc.data_available, "models_loaded": sorted(svc.models),
                  "model_errors": svc.model_errors, "device": str(svc.device),
                  "gpu": __import__("torch").cuda.get_device_name(0) if svc.device.type == "cuda" else None}
        return {"status": "ok" if db_ok else "degraded", "database": db_ok, "ml": ml}

    @router.post("/ingest")
    def ingest(body: IngestIn):
        rows = [FlowRecord(ts=f.ts, src_ip=f.src_ip, dst_ip=f.dst_ip, features=f.features, label=f.label,
                           window_id=body.window_id, task_id=body.task_id, split=body.split) for f in body.flows]
        with state.Session() as s:
            s.add_all(rows)
            s.commit()
            ids = [r.id for r in rows]
        return {"ingested": len(ids), "flow_ids": ids}

    @router.post("/predict")
    def predict(body: PredictIn):
        flows, flow_ids = None, None
        if body.flow_ids:
            with state.Session() as s:
                recs = s.scalars(select(FlowRecord).where(FlowRecord.id.in_(body.flow_ids))).all()
            recs = sorted(recs, key=lambda r: body.flow_ids.index(r.id))
            if not recs:
                raise HTTPException(404, "no flows found for flow_ids")
            flows = [{"src_ip": r.src_ip, "dst_ip": r.dst_ip, "features": r.features} for r in recs]
            flow_ids = [r.id for r in recs]
        elif body.flows:
            flows = [f.model_dump(mode="json") for f in body.flows]
        elif body.window_id is None:
            raise HTTPException(422, "provide flows, flow_ids or window_id")
        payload = {"flows": flows, "window_id": body.window_id, "models": body.models}
        if state.ml_url:
            result = _remote("POST", "/predict", json=payload)
        else:
            try:
                result = state.service.predict(**payload)
            except KeyError as exc:
                raise HTTPException(404, str(exc))
            except FileNotFoundError as exc:
                raise HTTPException(503, str(exc))
        # Stored here (not in the ML service) so it works in both deployment modes.
        if body.store and flow_ids:
            store_predictions(state.Session, flow_ids, result)
        return result

    @router.get("/metrics")
    def metrics(source: str = Query("continual", pattern="^(continual|stream)$"),
                run_id: str | None = None, model: str | None = None):
        with state.Session() as s:
            if source == "stream" and run_id is None:
                run_id = s.scalar(select(Metric.run_id).where(Metric.source == "stream")
                                  .order_by(desc(Metric.id)).limit(1))
            q = select(Metric).where(Metric.source == source)
            if run_id:
                q = q.where(Metric.run_id == run_id)
            if model:
                q = q.where(Metric.model_name == model)
            rows = s.scalars(q.order_by(Metric.id)).all()
        series: dict[str, list] = {}
        for r in rows:
            key = series_key(r.model_name, r.policy)
            series.setdefault(key, []).append({
                "ts": r.ts.isoformat() if r.ts else None, "task_id": r.task_id, "stream_index": r.stream_index,
                "accuracy": r.accuracy, "macro_f1": r.macro_f1, "retention_rate": r.retention_rate, "fpr": r.fpr,
                "retrains_so_far": r.retrains_so_far, "policy": r.policy, "run_id": r.run_id})
        return {"source": source, "run_id": run_id, "series": series}

    @router.get("/drift-status")
    def drift_status(run_id: str | None = None, limit: int = 50):
        with state.Session() as s:
            if run_id is None:
                run_id = s.scalar(select(DriftEventRow.run_id).order_by(desc(DriftEventRow.id)).limit(1))
            q = select(DriftEventRow)
            if run_id:
                q = q.where(DriftEventRow.run_id == run_id)
            events = s.scalars(q.order_by(desc(DriftEventRow.id)).limit(limit)).all()
            counts = s.execute(select(DriftEventRow.model_name, func.count(), func.sum(
                case((DriftEventRow.triggered_retrain, 1), else_=0)))
                .where(DriftEventRow.run_id == run_id).group_by(DriftEventRow.model_name)).all() if run_id else []
        demo = None
        if state.ml_url:
            try:
                demo = _remote("GET", "/demo/status")
            except HTTPException:
                demo = None
        else:  # same shape as the ML container's /demo/status
            demo = state.service.demo.describe() if state.service.demo is not None else {"status": "idle"}
        return {
            "run_id": run_id,
            "per_model": {m: {"drift_flags": int(n), "retrains_triggered": int(t or 0)} for m, n, t in counts},
            "events": [{"ts": e.ts.isoformat(), "model": e.model_name, "detector": e.detector,
                        "prev_error": e.prev_error, "new_error": e.new_error,
                        "triggered_retrain": e.triggered_retrain, "stream_index": e.stream_index,
                        "window_id": e.window_id, "reason": e.reason} for e in events],
            "demo": demo,
        }

    @router.get("/stream/windows")
    def stream_windows(run_id: str | None = None, since_index: int = -1, limit: int = 2000):
        with state.Session() as s:
            if run_id is None:
                run_id = s.scalar(select(WindowStat.run_id).order_by(desc(WindowStat.id)).limit(1))
            rows = s.scalars(select(WindowStat).where(WindowStat.run_id == run_id,
                                                      WindowStat.stream_index > since_index)
                             .order_by(WindowStat.id).limit(limit)).all() if run_id else []
        return {"run_id": run_id, "windows": [
            {k: getattr(r, k) for k in ("model_name", "stream_index", "window_id", "task_id", "n_flows",
                                        "error_rate", "pred_benign", "pred_known_attack", "pred_novel_drifted",
                                        "true_attack_fraction", "drift_flag", "retrained")} for r in rows]}

    @router.post("/retrain")
    def retrain():
        if state.ml_url:
            return _remote("POST", "/retrain")
        return state.service.request_retrain()

    @router.get("/graph/{window_id}")
    def graph(window_id: int, max_nodes: int = Query(150, ge=5, le=2000), model: str | None = None):
        if state.ml_url:
            params = {"max_nodes": max_nodes} | ({"model": model} if model else {})
            return _remote("GET", f"/graph/{window_id}", params=params)
        try:
            return state.service.graph_summary(window_id, max_nodes, model)
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc))

    @router.get("/windows")
    def windows(split: str | None = None, limit: int = 1000):
        with state.Session() as s:
            q = select(GraphWindow)
            if split:
                q = q.where(GraphWindow.split == split)
            rows = s.scalars(q.order_by(GraphWindow.id).limit(limit)).all()
        return [{"window_id": r.id, "task_id": r.task_id, "split": r.split, "n_nodes": r.n_nodes,
                 "n_edges": r.n_edges, "window_start": r.window_start.isoformat()} for r in rows]

    @router.get("/incidents/{window_id}")
    def incidents(window_id: int, model: str = "gnn_ewc_replay", threshold: float = Query(0.0, ge=0.0, le=1.0)):
        """Improvement 3: the window's flagged flows grouped into incidents, each with a proposed action."""
        if state.ml_url:
            return _remote("GET", f"/incidents/{window_id}", params={"model": model, "threshold": threshold})
        try:
            return state.service.incidents(window_id, model, threshold)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/explain/{window_id}/{edge}")
    def explain(window_id: int, edge: int, model: str = "gnn_ewc_replay"):
        """Improvement 2: feature, neighbourhood and structural evidence for one flow's verdict."""
        if state.ml_url:
            return _remote("GET", f"/explain/{window_id}/{edge}", params={"model": model})
        try:
            return state.service.explain(window_id, edge, model)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/actions")
    def propose(body: ProposeIn):
        """Improvement 15: record the proposed containment action for an incident (dry run)."""
        inc = incidents(body.window_id, body.model, 0.0)
        match = next((i for i in inc["incidents"] if i["incident_id"] == body.incident_id), None)
        if match is None:
            raise HTTPException(404, "incident not found")
        pr = match["proposed"]
        row = ResponseAction(window_id=body.window_id, incident_id=body.incident_id, model_name=body.model,
                             category=match["category"], action=pr["action"], target=pr["target"],
                             rationale=pr["rationale"], rule_linux=pr["rules"].get("linux"),
                             rule_windows=pr["rules"].get("windows"), status="proposed")
        with state.Session() as s:
            s.add(row)
            s.commit()
            return _action_dict(row)

    @router.post("/actions/{action_id}/decision")
    def decide(action_id: int, body: DecisionIn):
        """An analyst approves or rejects. Nothing is ever executed: approval is recorded as a dry run."""
        with state.Session() as s:
            row = s.get(ResponseAction, action_id)
            if row is None:
                raise HTTPException(404, "action not found")
            if row.status != "proposed":
                raise HTTPException(409, f"already {row.status}")
            row.status = "approved" if body.decision == "approve" else "rejected"
            row.decided_at = datetime.now(timezone.utc)
            row.decided_by, row.note = body.analyst, body.note
            s.commit()
            return _action_dict(row)

    @router.get("/actions")
    def actions(status: str | None = None, limit: int = Query(100, le=1000)):
        with state.Session() as s:
            q = select(ResponseAction)
            if status:
                q = q.where(ResponseAction.status == status)
            return [_action_dict(r) for r in s.scalars(q.order_by(desc(ResponseAction.id)).limit(limit)).all()]

    @router.get("/windows/catalog")
    def windows_catalog():
        """Every cached window with task, split and attack composition (Graph Explorer)."""
        if state.ml_url:
            return _remote("GET", "/windows/catalog")
        try:
            return state.service.list_windows()
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc))

    @router.post("/demo/start")
    def demo_start(body: DemoStartIn):
        if state.ml_url:
            return _remote("POST", "/demo/start", json=body.model_dump())
        try:
            return {"run_id": state.service.start_demo(body.delay_seconds, body.eval_every, body.max_windows)}
        except RuntimeError as exc:
            raise HTTPException(409, str(exc))
        except FileNotFoundError as exc:
            raise HTTPException(503, str(exc))

    @router.post("/demo/stop")
    def demo_stop():
        if state.ml_url:
            return _remote("POST", "/demo/stop")
        return {"stopped": state.service.stop_demo()}

    @router.get("/demo/status")
    def demo_status():
        if state.ml_url:
            return _remote("GET", "/demo/status")
        d = state.service.demo
        return d.describe() if d else {"status": "idle"}

    from src.api.results import router as results_router
    router.include_router(results_router)
    app.include_router(router)
    app.include_router(router, prefix="/api")

    dash = Path(os.environ.get("DASHBOARD_DIR", REPO_ROOT / "dashboard"))
    if dash.exists():
        app.mount("/dashboard", StaticFiles(directory=dash, html=True), name="dashboard")

        @app.get("/", include_in_schema=False)
        def root():
            return RedirectResponse("/dashboard/")
    return app


app = create_app()
