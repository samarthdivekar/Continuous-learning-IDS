"""Elastic Weight Consolidation (Kirkpatrick et al., 2017), online variant.

    L_total(θ) = L_task(θ) + (λ / 2) · Σ_i F_i · (θ_i − θ*_i)²

F   = diagonal (empirical) Fisher information, one value per parameter
θ*  = parameter values at the end of the last *completed* task

The model-agnostic implementation works for the E-GraphSAGE model and the
FFNN alike; it only touches `model.named_parameters()`.

---------------------------------------------------------------------------
The three implementation traps called out in the project brief, and how this
file avoids each one:

TRAP 1 — penalising against the task currently being learned.
    If θ* / F were refreshed *during* a task, the penalty would pull the
    weights back towards where they were a few steps ago, fighting the task
    gradient; with a large λ this oscillates and diverges to inf.
    → `penalty()` returns exactly 0 until `consolidate()` has been called,
      and `consolidate()` is only called by the trainer AFTER a task (or an
      adaptation cycle) has finished. θ* and F are therefore always from
      completed tasks. `self.frozen` snapshots are detached clones, so no
      gradient ever flows into them.

TRAP 2 — Fisher computed from the penalty-augmented gradient.
    If F were estimated from ∇(L_task + penalty), the penalty's own gradient
    λF(θ−θ*) would feed back into the next F estimate: importance becomes
    self-reinforcing and grows every task.
    → `consolidate()` takes a `loss_fn` that returns the RAW task loss only
      (cross-entropy on that task's data). It runs its own zero_grad /
      backward pass, never touches `penalty()`, and reads `.grad` directly.

TRAP 3 — lr · λ · F too large.
    For plain SGD the penalty term alone updates θ ← θ − lr·λ·F·(θ−θ*), which
    overshoots (and diverges) once lr·λ·F > 2. Adam rescales steps, which
    helps, but huge λF still makes training oscillate.
    → (a) F can be normalised per consolidation (`normalize="max"` divides by
      the largest entry, so max F = 1 per task and λ becomes interpretable
      across models), (b) `stability_ratio(lr)` = lr·λ·max(F) is logged after
      every consolidation and a warning is raised above `stability_warn`,
      (c) the trainer clips gradient norms, and (d) experiments/sweep_ewc_lambda.py
      sweeps λ on the validation split and logs every result.
---------------------------------------------------------------------------
"""
from __future__ import annotations

import warnings
from typing import Callable, Iterable

import torch
from torch import nn


class EWC:
    def __init__(self, model: nn.Module, lam: float, gamma: float = 1.0,
                 normalize: str = "max", stability_warn: float = 1.0):
        self.model = model
        self.lam = float(lam)
        self.gamma = float(gamma)          # online-EWC decay of old importance
        self.normalize = normalize
        self.stability_warn = float(stability_warn)
        self.fisher: dict[str, torch.Tensor] = {}
        self.frozen: dict[str, torch.Tensor] = {}   # θ* from the last completed task
        self.n_consolidations = 0
        self.history: list[dict] = []

    # ------------------------------------------------------------------
    @property
    def active(self) -> bool:
        """True only once at least one task has been consolidated (TRAP 1)."""
        return self.n_consolidations > 0 and self.lam > 0

    def penalty(self, model: nn.Module | None = None) -> torch.Tensor:
        model = model or self.model
        device = next(model.parameters()).device
        if not self.active:
            # No completed task yet -> no anchor -> no penalty. Returning a
            # constant zero keeps the training loop branch-free.
            return torch.zeros((), device=device)
        total = torch.zeros((), device=device)
        for name, p in model.named_parameters():
            if name in self.fisher:
                total = total + (self.fisher[name] * (p - self.frozen[name]) ** 2).sum()
        return 0.5 * self.lam * total

    # ------------------------------------------------------------------
    def estimate_fisher(self, batches: Iterable, loss_fn: Callable[[nn.Module, object], torch.Tensor],
                        max_batches: int | None = None) -> dict[str, torch.Tensor]:
        """Diagonal empirical Fisher: E_batches[(∂L_task/∂θ)²].

        `loss_fn(model, batch)` MUST return the plain task loss (no EWC term,
        no replay term) — see TRAP 2. We use mini-batch gradients (one graph
        or one flow mini-batch per sample), the usual practical approximation
        of per-example Fisher; the absolute scale is absorbed by
        normalisation and λ.
        """
        model = self.model
        was_training = model.training
        model.eval()  # deterministic forward (no dropout) for importance estimation
        fisher = {n: torch.zeros_like(p) for n, p in model.named_parameters() if p.requires_grad}
        n = 0
        for batch in batches:
            if max_batches is not None and n >= max_batches:
                break
            model.zero_grad(set_to_none=True)
            loss = loss_fn(model, batch)
            if not torch.isfinite(loss):
                continue
            loss.backward()
            for name, p in model.named_parameters():
                if p.grad is not None and name in fisher:
                    fisher[name] += p.grad.detach() ** 2
            n += 1
        model.zero_grad(set_to_none=True)
        model.train(was_training)
        if n == 0:
            raise RuntimeError("Fisher estimation saw no usable batches")
        for name in fisher:
            fisher[name] /= n
        if self.normalize == "max":
            m = max(f.max() for f in fisher.values())
            if m > 0:
                fisher = {k: v / m for k, v in fisher.items()}
        elif self.normalize == "mean":
            total = sum(f.sum() for f in fisher.values())
            count = sum(f.numel() for f in fisher.values())
            if total > 0:
                fisher = {k: v / (total / count) for k, v in fisher.items()}
        elif self.normalize != "none":
            raise ValueError(f"Unknown Fisher normalisation {self.normalize!r}")
        return fisher

    def consolidate(self, batches: Iterable, loss_fn: Callable, max_batches: int | None = None,
                    lr: float | None = None, tag: str = "") -> dict:
        """Call AFTER a task / adaptation cycle has finished training."""
        new_f = self.estimate_fisher(batches, loss_fn, max_batches)
        if not self.fisher:
            self.fisher = new_f
        else:
            # Online EWC: decayed sum of per-task importances, single anchor.
            self.fisher = {k: self.gamma * self.fisher[k] + new_f[k] for k in new_f}
        self.frozen = {n: p.detach().clone() for n, p in self.model.named_parameters() if n in self.fisher}
        self.n_consolidations += 1
        info = {"tag": tag, "consolidation": self.n_consolidations,
                "fisher_max": float(max(f.max() for f in self.fisher.values())),
                "fisher_mean": float(sum(f.sum() for f in self.fisher.values()) /
                                     sum(f.numel() for f in self.fisher.values()))}
        if lr is not None:
            info["stability_ratio"] = self.stability_ratio(lr)
            if info["stability_ratio"] > self.stability_warn:
                warnings.warn(f"EWC lr*lambda*max(F) = {info['stability_ratio']:.3g} exceeds "
                              f"{self.stability_warn}; training may oscillate or diverge (TRAP 3).")
        self.history.append(info)
        return info

    def stability_ratio(self, lr: float) -> float:
        if not self.fisher:
            return 0.0
        return float(lr * self.lam * max(f.max() for f in self.fisher.values()))

    # ------------------------------------------------------------------
    def state_dict(self) -> dict:
        return {"lam": self.lam, "gamma": self.gamma, "normalize": self.normalize,
                "fisher": {k: v.cpu() for k, v in self.fisher.items()},
                "frozen": {k: v.cpu() for k, v in self.frozen.items()},
                "n_consolidations": self.n_consolidations, "history": self.history}

    def load_state_dict(self, state: dict, device: torch.device) -> None:
        self.lam, self.gamma, self.normalize = state["lam"], state["gamma"], state["normalize"]
        self.fisher = {k: v.to(device) for k, v in state["fisher"].items()}
        self.frozen = {k: v.to(device) for k, v in state["frozen"].items()}
        self.n_consolidations = state["n_consolidations"]
        self.history = state.get("history", [])
