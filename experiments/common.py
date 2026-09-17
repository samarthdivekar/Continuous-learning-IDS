"""Shared CLI plumbing for experiment scripts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.config import load_config, resolve_path  # noqa: E402


def base_parser(description: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--dataset", default="cicids2017", choices=["cicids2017", "csecicids2018"])
    p.add_argument("--label-mode", default=None, choices=["multiclass", "binary"])
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--set", nargs="*", default=[], metavar="KEY=VALUE",
                   help="config overrides, e.g. ewc.lambda=10 window.flows_per_window=2000")
    p.add_argument("--dev", action="store_true",
                   help="development subsample: keep 20%% of windows per task (results go to results/dev/)")
    return p


def config_from_args(args) -> dict:
    overrides = list(args.set)
    if args.label_mode:
        overrides.append(f"label_mode={args.label_mode}")
    if args.seed is not None:
        overrides.append(f"seed={args.seed}")
    if args.dev:
        overrides.append("preprocessing.window_fraction=0.2")
    return load_config(args.dataset, overrides)


def selected_ewc_overrides(cfg: dict, args) -> dict:
    from src.utils.selection import selected_ewc_overrides as _sel
    return _sel(cfg, getattr(args, "dev", False))


def apply_selection(cfg: dict, args) -> dict:
    """Per-model EWC λ/γ from the validation sweep. Epoch settings selected by
    tune_val.py are already the defaults in configs/default.yaml, so CLI --set
    overrides are never silently replaced."""
    sel = selected_ewc_overrides(cfg, args)
    cfg = dict(cfg)
    cfg["model_overrides"] = sel["overrides"]
    cfg["ewc_selection_source"] = sel["source"]
    return cfg


def results_dir(cfg: dict, args, *parts: str) -> Path:
    base = resolve_path(cfg, "results")
    if getattr(args, "dev", False):
        base = base / "dev"
    return base.joinpath(cfg["dataset"], cfg["label_mode"], *parts)
