"""Validation-selected hyper-parameters, shared by experiments and the API service.

Two selection files, both produced on the VALIDATION split:
  results/<ds>/multiclass/tuning/selected.yaml          global overrides (epochs, replay loss)
  results/<ds>/multiclass/ewc_lambda_sweep/selected.json  λ/γ per EXACT model name

`<ds>` is cfg["tuning_from"] when set (CSE-CIC-IDS2018 reuses CIC-IDS2017's
selections), otherwise the dataset itself. Binary mode reuses the multiclass
selections.

Precedence (lowest -> highest): default.yaml < dataset overlay < tuning
selected.yaml < CLI --set. Per-model λ/γ from the sweep apply only to the model
they were selected for, and never to a key the user set explicitly on the CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.utils.config import resolve_path

EWC_KEYS = ("ewc.lambda", "ewc.gamma")


def _selection_root(cfg: dict, dev: bool) -> Path:
    ds = cfg.get("tuning_from") or cfg["dataset"]
    return resolve_path(cfg, "results") / ("dev" if dev else "") / ds


def tuning_overrides(cfg: dict, dev: bool = False) -> tuple[list[str], str | None]:
    base = _selection_root(cfg, dev)
    for mode in (cfg["label_mode"], "multiclass"):
        f = base / mode / "tuning" / "selected.yaml"
        if f.exists():
            return list((yaml.safe_load(f.read_text()) or {}).get("overrides", [])), str(f)
    return [], None


def selected_ewc_overrides(cfg: dict, dev: bool = False, cli_keys: set[str] | None = None) -> dict:
    """{"source": path|None, "overrides": {model_name: [k=v, ...]}}, exact model names only."""
    from src.training.learners import MODEL_SPECS  # local import: learners imports config utilities
    cli_keys = cli_keys or set()
    base = _selection_root(cfg, dev)
    for mode in (cfg["label_mode"], "multiclass"):
        f = base / mode / "ewc_lambda_sweep" / "selected.json"
        if f.exists():
            sel = json.loads(f.read_text())
            out = {}
            for model, v in sel.items():
                kv = [f"ewc.lambda={v['lambda']}", f"ewc.gamma={v['gamma']}"]
                kv = [x for x in kv if x.split("=")[0] not in cli_keys]
                if kv:
                    out[model] = kv
            # variants of a selected model (e.g. gnn_ewc_replay_topo) inherit its λ/γ,
            # so the only difference in the comparison is the variant itself
            for m, spec in MODEL_SPECS.items():
                if spec.get("base") in out and m not in out:
                    out[m] = list(out[spec["base"]])
            return {"source": str(f), "overrides": out, "skipped_cli_keys": sorted(cli_keys & set(EWC_KEYS))}
    return {"source": None, "overrides": {}, "skipped_cli_keys": []}


def apply_selection(cfg: dict, dev: bool = False, cli_overrides: list[str] | None = None) -> dict:
    """Apply tuning selected.yaml, re-apply CLI overrides on top, attach per-model EWC selections."""
    from src.utils.config import apply_overrides
    cli_overrides = list(cli_overrides or [])
    tun, tun_src = tuning_overrides(cfg, dev)
    if tun:
        cfg = apply_overrides(cfg, tun)
        cfg = apply_overrides(cfg, cli_overrides)  # CLI wins over the tuning file
    cli_keys = {o.split("=", 1)[0].strip() for o in cli_overrides if "=" in o}
    sel = selected_ewc_overrides(cfg, dev, cli_keys)
    cfg = dict(cfg)
    cfg["model_overrides"] = sel["overrides"]
    cfg["selection"] = {"tuning_source": tun_src, "tuning_overrides": tun, "ewc_source": sel["source"],
                        "ewc_per_model": sel["overrides"], "cli_keys_respected": sel["skipped_cli_keys"]}
    return cfg
