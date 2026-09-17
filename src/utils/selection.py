"""Validation-selected hyper-parameters, shared by experiments and the API service."""
from __future__ import annotations

import json

import yaml

from src.utils.config import apply_overrides, resolve_path


def selected_ewc_overrides(cfg: dict, dev: bool = False) -> dict:
    """EWC λ/γ per model family from the multiclass validation sweep (reused for
    binary mode). Returns {"source": path|None, "overrides": {model: [k=v, ...]}}."""
    from src.training.learners import MODEL_SPECS
    base = resolve_path(cfg, "results") / ("dev" if dev else "") / cfg["dataset"]
    for mode in (cfg["label_mode"], "multiclass"):
        f = base / mode / "ewc_lambda_sweep" / "selected.json"
        if f.exists():
            sel = json.loads(f.read_text())
            out = {}
            for model, v in sel.items():
                fam = MODEL_SPECS[model]["family"]
                for m, spec in MODEL_SPECS.items():
                    if spec["family"] == fam and spec.get("ewc"):
                        out[m] = [f"ewc.lambda={v['lambda']}", f"ewc.gamma={v['gamma']}"]
            return {"source": str(f), "overrides": out}
    return {"source": None, "overrides": {}}


def apply_selection(cfg: dict, dev: bool = False) -> dict:
    """Apply tuning/selected.yaml (global) and the EWC sweep selection (per model)."""
    base = resolve_path(cfg, "results") / ("dev" if dev else "") / cfg["dataset"]
    for mode in (cfg["label_mode"], "multiclass"):
        f = base / mode / "tuning" / "selected.yaml"
        if f.exists():
            cfg = apply_overrides(cfg, (yaml.safe_load(f.read_text()) or {}).get("overrides", []))
            break
    sel = selected_ewc_overrides(cfg, dev)
    cfg = dict(cfg)
    cfg["model_overrides"] = sel["overrides"]
    cfg["ewc_selection_source"] = sel["source"]
    return cfg
