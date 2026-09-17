"""Continual learners: a uniform interface over every model in the comparison.

    learner.learn(graphs, tag)        train on a list of window graphs (one task
                                      or one drift-triggered adaptation cycle)
    learner.predict_proba(graph)      (n_edges, n_classes) probabilities

All learners consume the SAME cached window graphs. Tabular learners (XGBoost,
FFNN) read `graph.edge_attr` / `graph.y` directly, so every model is trained
and evaluated on exactly the same flows with exactly the same features.

Strategies
    xgboost_static   fit on the first call only, frozen afterwards
    *_naive          fine-tune on the newest data only (no safeguards)
    *_ewc            + EWC penalty
    *_replay         + replay
    *_ewc_replay     + both (our method for the GNN; ablation for the FFNN)
    *_joint          retrain on ALL data seen so far (non-continual upper bound, reference only)

Ordering: tasks are presented strictly in chronological order. Inside one
task, windows (GNN) or flows (FFNN) are shuffled between epochs — ordinary
SGD on that task's data. Nothing from a future task is ever visible.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn.functional as F
from torch_geometric.data import Batch, Data

from src.graph.sampling import iter_training_subgraphs
from src.graph.window_builder import edge_labels
from src.models.baseline_xgb import StaticXGBoost
from src.models.egraphsage import EGraphSAGE
from src.models.ewc import EWC
from src.models.ffnn import FFNN
from src.models.replay_buffer import GraphReplayBuffer, TabularReplayBuffer
from src.utils.logging import get_logger

log = get_logger(__name__)

MODEL_SPECS = {
    "xgboost_static":   {"family": "xgb"},
    "gnn_naive":        {"family": "gnn", "ewc": False, "replay": False},
    "gnn_ewc":          {"family": "gnn", "ewc": True,  "replay": False},
    "gnn_replay":       {"family": "gnn", "ewc": False, "replay": True},
    "gnn_ewc_replay":   {"family": "gnn", "ewc": True,  "replay": True},
    "gnn_joint":        {"family": "gnn", "ewc": False, "replay": False, "joint": True},
    "ffnn_naive":       {"family": "ffnn", "ewc": False, "replay": False},
    "ffnn_ewc":         {"family": "ffnn", "ewc": True,  "replay": False},
    "ffnn_replay":      {"family": "ffnn", "ewc": False, "replay": True},
    "ffnn_ewc_replay":  {"family": "ffnn", "ewc": True,  "replay": True},
    "ffnn_joint":       {"family": "ffnn", "ewc": False, "replay": False, "joint": True},
}


def class_weights(labels: np.ndarray, num_classes: int, power: float, clip) -> torch.Tensor:
    """w_c = (N / (K_present * n_c)) ** power for classes present; 1.0 otherwise.

    Chosen over undersampling because undersampling benign traffic would delete
    edges and distort the graphs. power=0.5 (sqrt) tempers the weights so the
    rarest classes (WebAttack: ~100 flows) do not explode the false-positive rate.
    """
    counts = np.bincount(labels, minlength=num_classes).astype(np.float64)
    present = counts > 0
    w = np.ones(num_classes)
    if present.any():
        w[present] = (counts[present].sum() / (present.sum() * counts[present])) ** power
    w = np.clip(w, clip[0], clip[1])
    return torch.tensor(w, dtype=torch.float32)


@dataclass
class LearnStats:
    tag: str
    seconds: float
    steps: int
    final_loss: float
    extra: dict


class BaseLearner:
    name: str
    family: str

    def __init__(self, name: str, cfg: dict, n_features: int, num_classes: int, device: torch.device):
        self.name = name
        self.cfg = cfg
        self.spec = MODEL_SPECS[name]
        self.family = self.spec["family"]
        self.n_features = n_features
        self.num_classes = num_classes
        self.device = device
        self.label_mode = cfg["label_mode"]
        self.n_learn_calls = 0
        self.history: list[dict] = []

    def learn(self, graphs: list[Data], tag: str = "", epochs: int | None = None) -> LearnStats:
        raise NotImplementedError

    def predict_proba(self, g: Data) -> np.ndarray:
        raise NotImplementedError

    @property
    def adapts(self) -> bool:
        return self.family != "xgb"


# ---------------------------------------------------------------------------
class XGBLearner(BaseLearner):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.model = StaticXGBoost(self.num_classes, self.cfg["xgboost"], seed=self.cfg["seed"],
                                   device="cuda" if self.device.type == "cuda" else "cpu")

    def learn(self, graphs, tag="", epochs=None):
        t0 = time.time()
        if self.model.trained:
            return LearnStats(tag, 0.0, 0, float("nan"), {"frozen": True})
        X = torch.cat([g.edge_attr for g in graphs]).numpy()
        y = torch.cat([edge_labels(g, self.label_mode) for g in graphs]).numpy()
        tcfg = self.cfg["train"]
        w = class_weights(y, self.num_classes, tcfg["class_weight_power"], tcfg["class_weight_clip"]).numpy()
        self.model.fit(X, y, sample_weight=w[y])
        self.n_learn_calls += 1
        return LearnStats(tag, time.time() - t0, 1, float("nan"), {"n_train": len(y)})

    def predict_proba(self, g):
        return self.model.predict_proba(g.edge_attr.numpy())

    @property
    def adapts(self) -> bool:
        return False


# ---------------------------------------------------------------------------
class _TorchLearner(BaseLearner):
    """Shared optimiser / EWC / replay plumbing for GNN and FFNN learners."""

    def _post_init(self, model: torch.nn.Module):
        self.model = model.to(self.device)
        tcfg = self.cfg["train"]
        self.lr = float(tcfg["lr"])
        self.optimizer = self._make_optimizer()
        ecfg = self.cfg["ewc"]
        self.ewc = EWC(self.model, ecfg["lambda"], ecfg["gamma"], ecfg["normalize"], ecfg["stability_warn"]) \
            if self.spec.get("ewc") else None
        self.rng = np.random.default_rng(self.cfg["seed"])
        self.joint_store: list[Data] = []

    def _make_optimizer(self):
        tcfg = self.cfg["train"]
        if tcfg["optimizer"] == "sgd":
            return torch.optim.SGD(self.model.parameters(), lr=self.lr, momentum=0.9,
                                   weight_decay=tcfg["weight_decay"])
        return torch.optim.Adam(self.model.parameters(), lr=self.lr, weight_decay=tcfg["weight_decay"])

    def _step(self, loss: torch.Tensor) -> None:
        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.cfg["train"]["grad_clip"])
        self.optimizer.step()

    def _check_finite(self, loss: torch.Tensor, tag: str) -> None:
        if not torch.isfinite(loss):
            raise FloatingPointError(
                f"{self.name}: non-finite loss during '{tag}'. If EWC is enabled check "
                f"lr*lambda*max(F) (currently {self.ewc.stability_ratio(self.lr) if self.ewc else 'n/a'}).")


# ---------------------------------------------------------------------------
class GNNLearner(_TorchLearner):
    def __init__(self, *a, node_in: int = 3, **kw):
        super().__init__(*a, **kw)
        gcfg = self.cfg["graph"]
        self.node_in = node_in
        self._post_init(EGraphSAGE(node_in, self.n_features, self.num_classes, gcfg["hidden"],
                                   gcfg["layers"], gcfg["dropout"], gcfg["edge_skip"]))
        rcfg = self.cfg["replay"]
        self.buffer = GraphReplayBuffer(rcfg["graphs_per_class"], rcfg["graphs_per_step"],
                                        rcfg["min_class_edges"], seed=self.cfg["seed"]) \
            if self.spec.get("replay") else None

    # -- loss helpers --------------------------------------------------------
    def _labels(self, g) -> torch.Tensor:
        return edge_labels(g, self.label_mode)

    def _loss_on(self, sub: Data, weight: torch.Tensor, category_balanced: bool = False) -> torch.Tensor:
        sub = sub.to(self.device)
        logits = self.model(sub.x, sub.edge_index, sub.edge_attr)
        mask = sub.target_mask
        if not category_balanced:
            return F.cross_entropy(logits[mask], self._labels(sub)[mask], weight=weight)
        # Category-balanced replay loss: mean CE per category, then mean over
        # categories. A replayed WebAttack window holds a handful of attack
        # edges among ~5k benign ones; a plain edge-mean would let benign edges
        # swamp the very category the window was stored to preserve. The FFNN
        # buffer gets the same effect by sampling rows category-balanced, so
        # this keeps the FFNN-vs-GNN comparison symmetric.
        per_edge = F.cross_entropy(logits[mask], self._labels(sub)[mask], reduction="none")
        cats = sub.y[mask]
        present = torch.unique(cats)
        return torch.stack([per_edge[cats == c].mean() for c in present]).mean()

    def _raw_task_loss(self, model, g: Data) -> torch.Tensor:
        """Plain CE on one window — used for Fisher estimation (EWC TRAP 2: no penalty, no replay)."""
        sub = next(iter_training_subgraphs(g, self.cfg["graph"]["neighbor_sampling"], self.rng))
        sub = sub.to(self.device)
        logits = model(sub.x, sub.edge_index, sub.edge_attr)
        return F.cross_entropy(logits[sub.target_mask], self._labels(sub)[sub.target_mask])

    def learn(self, graphs: list[Data], tag: str = "", epochs: int | None = None) -> LearnStats:
        t0 = time.time()
        if not graphs:
            return LearnStats(tag, 0.0, 0, float("nan"), {"skipped": "no graphs"})
        tcfg, rcfg, ns = self.cfg["train"], self.cfg["replay"], self.cfg["graph"]["neighbor_sampling"]
        epochs = epochs or tcfg["gnn_epochs"]

        if self.spec.get("joint"):
            self.joint_store.extend(graphs)
            train_graphs = self.joint_store
        else:
            train_graphs = graphs

        labels = torch.cat([self._labels(g) for g in train_graphs]).numpy()
        weight = class_weights(labels, self.num_classes, tcfg["class_weight_power"],
                               tcfg["class_weight_clip"]).to(self.device)
        self.model.train()
        steps, last = 0, float("nan")
        for _ in range(epochs):
            for gi in self.rng.permutation(len(train_graphs)):
                for sub in iter_training_subgraphs(train_graphs[gi], ns, self.rng):
                    loss = self._loss_on(sub, weight)
                    replay_loss = torch.zeros((), device=self.device)
                    if self.buffer is not None and self.buffer.categories:
                        # Fixed replay budget per step (see replay_buffer.py). Stored
                        # windows are batched into one disjoint-union graph.
                        replayed = [next(iter_training_subgraphs(r, ns, self.rng))
                                    for r in self.buffer.sample()]
                        if replayed:
                            rb = Batch.from_data_list(replayed)
                            replay_loss = self._loss_on(rb, weight,
                                                        category_balanced=rcfg.get("category_balanced_loss", False))
                    penalty = self.ewc.penalty() if self.ewc is not None else 0.0
                    total = loss + rcfg["replay_weight"] * replay_loss + penalty
                    self._check_finite(total, tag)
                    self._step(total)
                    steps += 1
                    last = float(total.detach())

        extra = {}
        # ---- consolidation happens only AFTER training finished (EWC TRAP 1) ----
        if self.ewc is not None:
            idx = self.rng.permutation(len(graphs))[: self.cfg["ewc"]["fisher_batches"]]
            info = self.ewc.consolidate((graphs[i] for i in idx), self._raw_task_loss,
                                        lr=self.lr, tag=tag)
            extra["ewc"] = info
        if self.buffer is not None:
            self.buffer.add_many(graphs)
            extra["buffer"] = self.buffer.summary()
        self.n_learn_calls += 1
        stats = LearnStats(tag, time.time() - t0, steps, last, extra)
        self.history.append(stats.__dict__)
        return stats

    @torch.no_grad()
    def predict_proba(self, g: Data) -> np.ndarray:
        self.model.eval()
        # NB: Data.to() is in-place in PyG; never call it on cached graphs.
        logits = self.model(g.x.to(self.device), g.edge_index.to(self.device), g.edge_attr.to(self.device))
        return torch.softmax(logits, dim=-1).cpu().numpy()


# ---------------------------------------------------------------------------
class FFNNLearner(_TorchLearner):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        fcfg = self.cfg["ffnn"]
        self._post_init(FFNN(self.n_features, self.num_classes, tuple(fcfg["hidden"]), fcfg["dropout"]))
        rcfg = self.cfg["replay"]
        self.buffer = TabularReplayBuffer(rcfg["flows_per_class"], rcfg["flows_per_step"], seed=self.cfg["seed"]) \
            if self.spec.get("replay") else None
        self.joint_X: list[np.ndarray] = []
        self.joint_y: list[np.ndarray] = []

    def _to_labels(self, y_cat: np.ndarray) -> np.ndarray:
        return (y_cat > 0).astype(np.int64) if self.label_mode == "binary" else y_cat.astype(np.int64)

    def _raw_task_loss(self, model, batch) -> torch.Tensor:
        xb, yb = batch
        return F.cross_entropy(model(xb), yb)   # EWC TRAP 2: raw task loss only

    def learn(self, graphs: list[Data], tag: str = "", epochs: int | None = None) -> LearnStats:
        t0 = time.time()
        if not graphs:
            return LearnStats(tag, 0.0, 0, float("nan"), {"skipped": "no graphs"})
        tcfg, rcfg = self.cfg["train"], self.cfg["replay"]
        epochs = epochs or tcfg["ffnn_epochs"]
        X_new = torch.cat([g.edge_attr for g in graphs]).numpy()
        ycat_new = torch.cat([g.y for g in graphs]).numpy()
        if self.spec.get("joint"):
            self.joint_X.append(X_new)
            self.joint_y.append(ycat_new)
            X, ycat = np.concatenate(self.joint_X), np.concatenate(self.joint_y)
        else:
            X, ycat = X_new, ycat_new
        y = self._to_labels(ycat)
        weight = class_weights(y, self.num_classes, tcfg["class_weight_power"],
                               tcfg["class_weight_clip"]).to(self.device)

        # Small matrices live on the GPU; large ones (e.g. joint training on 2018,
        # ~2 GB) stay in host memory and only mini-batches are transferred.
        on_device = X.nbytes < 1_000_000_000
        store = self.device if on_device else torch.device("cpu")
        Xt = torch.from_numpy(X).to(store)
        yt = torch.from_numpy(y).to(store)
        bs = int(tcfg["ffnn_batch_size"])
        self.model.train()
        steps, last = 0, float("nan")
        for _ in range(epochs):
            perm = torch.from_numpy(self.rng.permutation(len(y))).to(store)
            for s in range(0, len(y), bs):
                idx = perm[s:s + bs]
                xb, yb = Xt[idx].to(self.device, non_blocking=True), yt[idx].to(self.device, non_blocking=True)
                loss = F.cross_entropy(self.model(xb), yb, weight=weight)
                replay_loss = torch.zeros((), device=self.device)
                if self.buffer is not None and self.buffer.categories:
                    rX, rcat = self.buffer.sample()
                    rX = torch.from_numpy(rX).to(self.device)
                    ry = torch.from_numpy(self._to_labels(rcat)).to(self.device)
                    replay_loss = F.cross_entropy(self.model(rX), ry, weight=weight)
                penalty = self.ewc.penalty() if self.ewc is not None else 0.0
                total = loss + rcfg["replay_weight"] * replay_loss + penalty
                self._check_finite(total, tag)
                self._step(total)
                steps += 1
                last = float(total.detach())

        extra = {}
        if self.ewc is not None:   # after training only (TRAP 1)
            n_new = len(X_new)
            Xn = torch.from_numpy(X_new).to(self.device)
            yn = torch.from_numpy(self._to_labels(ycat_new)).to(self.device)
            order = torch.from_numpy(self.rng.permutation(n_new)).to(self.device)
            batches = ((Xn[order[s:s + bs]], yn[order[s:s + bs]]) for s in range(0, n_new, bs))
            extra["ewc"] = self.ewc.consolidate(batches, self._raw_task_loss,
                                                max_batches=self.cfg["ewc"]["fisher_batches"], lr=self.lr, tag=tag)
        if self.buffer is not None:
            self.buffer.add(X_new, ycat_new)
            extra["buffer"] = self.buffer.summary()
        self.n_learn_calls += 1
        stats = LearnStats(tag, time.time() - t0, steps, last, extra)
        self.history.append(stats.__dict__)
        return stats

    @torch.no_grad()
    def predict_proba(self, g: Data) -> np.ndarray:
        self.model.eval()
        out = []
        X = g.edge_attr
        for s in range(0, len(X), 65536):
            out.append(torch.softmax(self.model(X[s:s + 65536].to(self.device)), dim=-1).cpu())
        return torch.cat(out).numpy()


def make_learner(name: str, cfg: dict, n_features: int, num_classes: int, device: torch.device,
                 node_in: int = 3) -> BaseLearner:
    """`cfg["model_overrides"][name]` (list of key=value) is applied for this model
    only, e.g. a λ selected separately for the GNN and the FFNN."""
    per_model = (cfg.get("model_overrides") or {}).get(name)
    if per_model:
        from src.utils.config import apply_overrides
        cfg = apply_overrides(cfg, per_model)
    fam = MODEL_SPECS[name]["family"]
    if fam == "xgb":
        return XGBLearner(name, cfg, n_features, num_classes, device)
    if fam == "gnn":
        return GNNLearner(name, cfg, n_features, num_classes, device, node_in=node_in)
    return FFNNLearner(name, cfg, n_features, num_classes, device)


def snapshot(learner: BaseLearner) -> BaseLearner:
    """Deep copy (used by the drift experiment to branch a learner)."""
    return copy.deepcopy(learner)
