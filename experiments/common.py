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


def cli_overrides(args) -> list[str]:
    overrides = list(args.set)
    if args.label_mode:
        overrides.append(f"label_mode={args.label_mode}")
    if args.seed is not None:
        overrides.append(f"seed={args.seed}")
    if args.dev:
        overrides.append("preprocessing.window_fraction=0.2")
    return overrides


def config_from_args(args) -> dict:
    """default.yaml < dataset overlay < CLI. No validation selections applied
    (used by tune_val, which produces them)."""
    return load_config(args.dataset, cli_overrides(args))


def apply_tuning(cfg: dict, args) -> dict:
    """Apply tuning/selected.yaml only (used by the λ sweep, which produces the EWC selection)."""
    from src.utils.config import apply_overrides
    from src.utils.selection import tuning_overrides
    tun, src = tuning_overrides(cfg, getattr(args, "dev", False))
    cfg = apply_overrides(apply_overrides(cfg, tun), cli_overrides(args))
    cfg["selection"] = {"tuning_source": src, "tuning_overrides": tun}
    return cfg


def apply_selection(cfg: dict, args) -> dict:
    """Tuning selected.yaml + per-model EWC λ/γ from the validation sweep.
    CLI --set values always win (see src/utils/selection.py)."""
    from src.utils.selection import apply_selection as _apply
    return _apply(cfg, getattr(args, "dev", False), cli_overrides(args))


def results_dir(cfg: dict, args, *parts: str) -> Path:
    base = resolve_path(cfg, "results")
    if getattr(args, "dev", False):
        base = base / "dev"
    return base.joinpath(cfg["dataset"], cfg["label_mode"], *parts)
