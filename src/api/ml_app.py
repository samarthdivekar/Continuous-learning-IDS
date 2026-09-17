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
            "model_errors": svc.model_errors, "device": str(svc.device)}


@app.post("/predict")
def predict(body: PredictBody):
    try:
        return svc.predict(flows=body.flows, window_id=body.window_id, models=body.models)
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.post("/retrain")
def retrain():
    return svc.request_retrain()


@app.get("/graph/{window_id}")
def graph(window_id: int, max_nodes: int = 150):
    try:
        return svc.graph_summary(window_id, max_nodes)
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
