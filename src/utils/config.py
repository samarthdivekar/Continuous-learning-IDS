"""Configuration loading: default.yaml <- dataset overlay <- CLI overrides."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterable

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"


def deep_merge(base: dict, overlay: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _parse_value(raw: str) -> Any:
    # YAML parsing gives us ints/floats/bools/lists/null for free.
    return yaml.safe_load(raw)


def apply_overrides(cfg: dict, overrides: Iterable[str]) -> dict:
    """Apply `a.b.c=value` style overrides."""
    cfg = copy.deepcopy(cfg)
    for item in overrides or []:
        if "=" not in item:
            raise ValueError(f"Override must look like key.path=value, got {item!r}")
        key, raw = item.split("=", 1)
        node = cfg
        parts = key.strip().split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = _parse_value(raw)
    return cfg


def load_config(dataset: str | None = None, overrides: Iterable[str] | None = None,
                config_path: str | Path | None = None) -> dict:
    with open(config_path or CONFIG_DIR / "default.yaml", "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    dataset = dataset or cfg.get("dataset")
    overlay_path = CONFIG_DIR / f"{dataset}.yaml"
    if overlay_path.exists():
        with open(overlay_path, "r", encoding="utf-8") as fh:
            cfg = deep_merge(cfg, yaml.safe_load(fh) or {})
    cfg["dataset"] = dataset
    cfg = apply_overrides(cfg, overrides)
    return cfg


def resolve_path(cfg: dict, key: str) -> Path:
    p = Path(cfg["paths"][key])
    return p if p.is_absolute() else REPO_ROOT / p


def num_classes(cfg: dict) -> int:
    return 2 if cfg["label_mode"] == "binary" else len(cfg["categories"])


def class_names(cfg: dict) -> list[str]:
    return ["Benign", "Attack"] if cfg["label_mode"] == "binary" else list(cfg["categories"])
