"""Loading model checkpoints without handing an attacker a shell.

`torch.load` unpickles, and unpickling arbitrary data runs arbitrary code: a swapped
checkpoint file is remote code execution. PyTorch's `weights_only=True` reader accepts
only tensors and plain containers, which is all our checkpoints contain
(see `save_checkpoint`: a state_dict, a name, and EWC's tensors and floats).

So: always read in the safe mode. Only if that fails do we fall back to the full
unpickler, and only for files that live inside this project's own checkpoint directory
(written by our own experiments, not downloaded) — an older checkpoint keeps working
while a file from anywhere else is refused.
"""
from __future__ import annotations

import logging
from pathlib import Path

import torch

from src.utils.config import REPO_ROOT

log = logging.getLogger(__name__)


def _is_local_artifact(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    roots = [(REPO_ROOT / "cache").resolve(), (REPO_ROOT / "results").resolve()]
    # cache/ is often a junction to another drive; compare the real targets
    return any(str(resolved).startswith(str(root)) for root in roots)


def load_checkpoint(path: str | Path, map_location=None):
    """Checkpoint contents, read with weights_only=True whenever possible."""
    path = Path(path)
    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except Exception as exc:                       # pickle.UnpicklingError and friends
        if not _is_local_artifact(path):
            raise RuntimeError(
                f"{path} could not be read in PyTorch's safe mode and is outside this project's own "
                f"cache/ and results/ directories, so it will not be unpickled. Re-train the model or "
                f"move the file into cache/checkpoints/ if you trust it. Original error: {exc}") from exc
        log.warning("%s is not weights_only-safe; falling back to the full unpickler because it is a "
                    "locally produced artifact (%s)", path.name, exc)
        return torch.load(path, map_location=map_location, weights_only=False)
