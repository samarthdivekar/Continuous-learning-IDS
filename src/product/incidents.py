"""Incident-level alerting with a false-alarm budget (improvement 3).

Flow-level alerts are grouped into INCIDENTS: connected components of the graph
formed by the flagged flows of one predicted category. One scanner → one
incident; a DDoS against one victim → one incident; scattered false alarms stay
small and separate. Analysts triage incidents, not thousands of flows.

False-alarm budget: an alert is raised only if the model's confidence in the
attack class is ≥ τ, where τ is calibrated on VALIDATION benign flows so that
at most `budget` of them would alert.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np


def calibrate_threshold(probs: np.ndarray, y: np.ndarray, budget: float, benign: int = 0) -> float:
    """Smallest τ such that ≤ `budget` of validation benign flows get attack confidence ≥ τ."""
    ben = probs[y == benign]
    if len(ben) == 0 or budget <= 0:
        return 1.0
    attack_conf = 1.0 - ben[:, benign]                 # probability mass on ANY attack class
    return float(np.quantile(attack_conf, 1.0 - budget))


class _DSU:
    def __init__(self):
        self.p = {}

    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def build_incidents(src: np.ndarray, dst: np.ndarray, probs: np.ndarray, class_names: list[str],
                    threshold: float = 0.5, ts: np.ndarray | None = None, y_cat: np.ndarray | None = None,
                    benign: int = 0, min_flows: int = 1) -> list[dict]:
    pred = probs.argmax(1)
    attack_conf = 1.0 - probs[:, benign]
    flagged = np.flatnonzero((pred != benign) & (attack_conf >= threshold))
    groups = defaultdict(list)
    for c in np.unique(pred[flagged]):
        idx = flagged[pred[flagged] == c]
        dsu = _DSU()
        for i in idx:
            dsu.union(("h", src[i]), ("h", dst[i]))
        for i in idx:
            groups[(int(c), dsu.find(("h", src[i])))].append(i)
    incidents = []
    for (c, _), idx in groups.items():
        idx = np.asarray(idx)
        if len(idx) < min_flows:
            continue
        hosts_s, cnt_s = np.unique(src[idx], return_counts=True)
        hosts_d, cnt_d = np.unique(dst[idx], return_counts=True)
        # the "key" host: the busiest one (scanner / attacker, or the DDoS victim)
        if cnt_s.max() >= cnt_d.max():
            key, role, deg = hosts_s[cnt_s.argmax()], "source", int(cnt_s.max())
        else:
            key, role, deg = hosts_d[cnt_d.argmax()], "destination", int(cnt_d.max())
        inc = {"category": class_names[c], "category_id": c, "n_flows": int(len(idx)),
               "n_sources": int(len(hosts_s)), "n_destinations": int(len(hosts_d)),
               "key_host": str(key), "key_role": role, "key_host_flows": deg,
               "mean_confidence": float(attack_conf[idx].mean()),
               "severity": float(np.log1p(len(idx)) * attack_conf[idx].mean()),
               "flow_indices": idx.tolist()}
        if ts is not None:
            inc["start"], inc["end"] = str(np.min(ts[idx])), str(np.max(ts[idx]))
        if y_cat is not None:
            inc["true_attack_share"] = float((y_cat[idx] != benign).mean())
        incidents.append(inc)
    incidents.sort(key=lambda d: -d["severity"])
    for k, inc in enumerate(incidents):
        inc["incident_id"] = k + 1
    return incidents


def incident_metrics(incidents: list[dict], y_cat: np.ndarray, benign: int = 0) -> dict:
    """Precision at incident level (majority of flows truly malicious) and how much
    of the real attack traffic sits inside a true incident."""
    n_att = int((y_cat != benign).sum())
    true_inc = [i for i in incidents if i.get("true_attack_share", 0) > 0.5]
    covered = sum(int((y_cat[np.asarray(i["flow_indices"])] != benign).sum()) for i in true_inc)
    return {"incidents": len(incidents), "true_incidents": len(true_inc),
            "incident_precision": len(true_inc) / len(incidents) if incidents else float("nan"),
            "flagged_flows": int(sum(i["n_flows"] for i in incidents)),
            "attack_flows_in_true_incidents": covered / n_att if n_att else float("nan")}
