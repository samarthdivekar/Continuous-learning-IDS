"""ML service container (brief §8, layer 3).

    uvicorn src.api.ml_app:app --port 8001

Owns the models, the cached graphs and the live demo thread. The public API
forwards /predict, /retrain, /graph and /demo/* here when ML_SERVICE_URL is set.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from src.api.service import MLService
from src.db.session import get_sessionmaker

svc: MLService | None = None


class PredictBody(BaseModel):
    flows: list[dict] | None = None
    window_id: int | None = None
    models: list[str] | None = None


class DemoBody(BaseModel):
    delay_seconds: float = 0.5
    eval_every: int = 10
    max_windows: int | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global svc
    svc = MLService(session_factory=get_sessionmaker())
    svc.load_models()
    yield
    svc.stop_demo()


app = FastAPI(title="GNN-IDS ML service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "dataset": svc.cfg["dataset"], "label_mode": svc.cfg["label_mode"],
            "data_available": svc.data_available, "models_loaded": sorted(svc.models),
            "model_errors": svc.model_errors, "device": str(svc.device), "gpu": _gpu_name(),
            "drift_detector": _drift_status()}


def _drift_status():
    """ADWIN needs river, whose compiled extension some machines block: say so instead of failing."""
    from src.drift.adwin_monitor import river_available
    ok, reason = river_available()
    return {"available": ok, "reason": reason}


def _gpu_name():
    import torch
    return torch.cuda.get_device_name(0) if torch.cuda.is_available() and svc.device.type == "cuda" else None


@app.post("/predict")
def predict(body: PredictBody):
    try:
        return svc.predict(flows=body.flows, window_id=body.window_id, models=body.models)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:                  # MissingFeaturesError: incomplete flows are rejected, not imputed
        raise HTTPException(422, str(exc))


@app.get("/incidents/scan")
def scan_incidents(limit: int = 20, model: str = "gnn_ewc_replay", threshold: float = 0.0):
    try:
        return svc.scan_incidents(limit, model, threshold)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/incidents/{window_id}")
def incidents(window_id: int, model: str = "gnn_ewc_replay", threshold: float = 0.0):
    try:
        return svc.incidents(window_id, model, threshold)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/incidents/{window_id}/report")
def incident_report(window_id: int, incident_id: int, model: str = "gnn_ewc_replay", threshold: float = 0.0):
    try:
        return svc.incident_report(window_id, incident_id, model, threshold)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/explain/{window_id}/{edge}")
def explain(window_id: int, edge: int, model: str = "gnn_ewc_replay"):
    try:
        return svc.explain(window_id, edge, model)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/windows/catalog")
def windows_catalog():
    return svc.list_windows()


@app.post("/retrain")
def retrain():
    return svc.request_retrain()


@app.get("/graph/{window_id}")
def graph(window_id: int, max_nodes: int = 150, model: str | None = None):
    try:
        return svc.graph_summary(window_id, max_nodes, model)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.post("/demo/start")
def demo_start(body: DemoBody):
    try:
        return {"run_id": svc.start_demo(body.delay_seconds, body.eval_every, body.max_windows)}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/demo/stop")
def demo_stop():
    return {"stopped": svc.stop_demo()}


@app.get("/demo/status")
def demo_status():
    return svc.demo.describe() if svc.demo else {"status": "idle"}


# ------------------------------------------------------------------ live traffic (src/live)
class LiveScoreBody(BaseModel):
    flows: list[dict]
    context: list[dict] = []


class LiveAdaptBody(BaseModel):
    windows: list[dict]          # [{"flows": [...], "labels": [label name or null per flow]}]
    epochs: int | None = None
    holdout_benign: list[dict] | None = None


@app.post("/live/score")
def live_score(body: LiveScoreBody):
    try:
        return svc.live.score(body.flows, body.context)
    except ValueError as exc:                  # MissingFeaturesError
        raise HTTPException(422, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


@app.post("/live/adapt")
def live_adapt(body: LiveAdaptBody):
    from src.live.engine import label_id
    try:
        names = svc.live.names
        windows = [(w["flows"], [label_id(names, lab) for lab in w["labels"]]) for w in body.windows]
        return svc.live.adapt(windows, epochs=body.epochs, holdout_benign=body.holdout_benign)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


class LiveFprBody(BaseModel):
    flows: list[dict]
    teach_fraction: float = 0.5
    epochs: int | None = None


@app.post("/live/fpr_study")
def live_fpr_study(body: LiveFprBody):
    try:
        return svc.live.fpr_study(body.flows, teach_fraction=body.teach_fraction, epochs=body.epochs)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


@app.get("/live/recorded_flows")
def live_recorded_flows(category: str, n: int = 5000):
    try:
        return {"category": category, "flows": svc.recorded_flows(category, n)}
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc))


@app.post("/live/reset")
def live_reset():
    return svc.live.reset()


@app.get("/live/model")
def live_model():
    return svc.live.describe()
