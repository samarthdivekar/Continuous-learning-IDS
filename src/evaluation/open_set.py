"""Open-set novelty detection: flag flows that belong to NO known class, before
anyone has labelled the new attack, and propose new categories by clustering.

Scores (higher = more novel), computed only over the classes the model has
actually been trained on so far ("known"):
  msp        1 − max softmax probability                    (Hendrycks & Gimpel 2017)
  energy     −logsumexp(logits over known classes)          (Liu et al. 2020)
  prototype  cosine distance from the flow's embedding to the nearest
             known-class mean embedding                     (prototype / nearest-class-mean)

Thresholds are calibrated on VALIDATION flows of known classes at a target
false-alarm rate (default 5 %): nothing about the novel attack is used.
"""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import roc_auc_score, silhouette_score

METHODS = ("msp", "energy", "prototype")


def _normalize(z: np.ndarray) -> np.ndarray:
    return z / np.maximum(np.linalg.norm(z, axis=1, keepdims=True), 1e-8)


def fit_prototypes(z: np.ndarray, y: np.ndarray, known: list[int], max_per_class: int = 20000,
                   seed: int = 0) -> dict[int, np.ndarray]:
    rng = np.random.default_rng(seed)
    zn = _normalize(z)
    protos = {}
    for c in known:
        idx = np.flatnonzero(y == c)
        if len(idx) == 0:
            continue
        if len(idx) > max_per_class:
            idx = rng.choice(idx, max_per_class, replace=False)
        m = zn[idx].mean(axis=0)
        protos[c] = m / max(np.linalg.norm(m), 1e-8)
    return protos


def novelty_scores(logits: np.ndarray, z: np.ndarray | None, known: list[int],
                   prototypes: dict[int, np.ndarray] | None) -> dict[str, np.ndarray]:
    lk = logits[:, known]
    lk = lk - lk.max(axis=1, keepdims=True)
    p = np.exp(lk)
    p /= p.sum(axis=1, keepdims=True)
    out = {"msp": 1.0 - p.max(axis=1),
           "energy": -(np.log(np.exp(lk).sum(axis=1)) + logits[:, known].max(axis=1))}
    if z is not None and prototypes:
        P = np.stack([prototypes[c] for c in prototypes])
        out["prototype"] = 1.0 - (_normalize(z) @ P.T).max(axis=1)
    return out


def calibrate(val_known_scores: np.ndarray, target_fpr: float = 0.05) -> float:
    """Threshold so that `target_fpr` of known validation flows would be flagged."""
    return float(np.quantile(val_known_scores, 1.0 - target_fpr))


def detection_metrics(known: np.ndarray, novel: np.ndarray, threshold: float) -> dict:
    y = np.r_[np.zeros(len(known)), np.ones(len(novel))]
    s = np.r_[known, novel]
    auroc = float(roc_auc_score(y, s)) if len(known) and len(novel) else float("nan")
    return {"auroc": auroc, "tpr": float((novel > threshold).mean()) if len(novel) else float("nan"),
            "fpr_known": float((known > threshold).mean()) if len(known) else float("nan"),
            "n_known": int(len(known)), "n_novel": int(len(novel))}


def propose_clusters(z_flagged: np.ndarray, cat_flagged: np.ndarray, k_range=range(2, 7),
                     max_points: int = 20000, seed: int = 0) -> dict:
    """Cluster flagged flows; report how pure the proposed 'new category' is.

    The analyst would be shown the largest cluster as a candidate new class.
    `purity_largest` = share of its flows that truly belong to its majority
    category; `majority_category` is what it actually is (unknown to the model).
    """
    n = len(z_flagged)
    if n < 10:
        return {"n_flagged": n, "k": 0, "purity_largest": float("nan"), "majority_category": None,
                "weighted_purity": float("nan")}
    rng = np.random.default_rng(seed)
    idx = rng.choice(n, min(n, max_points), replace=False)
    Z, C = _normalize(z_flagged[idx]), cat_flagged[idx]
    best = None
    for k in [k for k in k_range if k < len(Z)]:
        km = KMeans(n_clusters=k, n_init=5, random_state=seed).fit(Z)
        sil = silhouette_score(Z, km.labels_, sample_size=min(len(Z), 5000), random_state=seed)
        if best is None or sil > best[0]:
            best = (sil, k, km.labels_)
    _, k, lab = best
    sizes = np.bincount(lab)
    big = int(sizes.argmax())
    members = C[lab == big]
    vals, cnt = np.unique(members, return_counts=True)
    weighted = sum(np.bincount(C[lab == j]).max() for j in range(k)) / len(C)
    return {"n_flagged": n, "k": int(k), "largest_cluster_share": float(sizes[big] / len(C)),
            "purity_largest": float(cnt.max() / len(members)), "majority_category": int(vals[cnt.argmax()]),
            "weighted_purity": float(weighted)}
