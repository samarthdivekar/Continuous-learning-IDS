"""Seeding, device selection and run metadata (recorded next to every result)."""
from __future__ import annotations

import json
import os
import platform
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    # Deterministic cuDNN kernels. Scatter ops on CUDA are still not bit-exact
    # across runs; this is recorded in run_info and discussed in the README.
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


def get_device(pref: str = "auto") -> torch.device:
    if pref == "cpu":
        return torch.device("cpu")
    if pref == "cuda" or (pref == "auto" and torch.cuda.is_available()):
        return torch.device("cuda")
    return torch.device("cpu")


def _pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def run_info(cfg: dict, extra: dict | None = None) -> dict:
    info = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "seed": cfg.get("seed"),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "packages": {p: _pkg_version(p) for p in
                     ["torch", "torch-geometric", "xgboost", "scikit-learn", "river", "pandas", "numpy"]},
        "command": " ".join(sys.argv),
        "config": cfg,
    }
    if extra:
        info.update(extra)
    return info


def write_run_info(path: Path, cfg: dict, extra: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(run_info(cfg, extra), fh, indent=2, default=str)
