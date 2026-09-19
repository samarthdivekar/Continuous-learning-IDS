"""Per-alert explanations (improvement 2).

For one flow (edge) in a window graph:
  * feature evidence   gradient × input of the predicted class's logit w.r.t. the
                       flow's own features (fast, exact first-order attribution),
                       reported with the value in original units
  * context evidence   the same gradient w.r.t. every OTHER flow's features,
                       aggregated per flow — which neighbouring flows the GNN
                       leaned on (only meaningful for the graph model)
  * structure facts    fan-out of the source host, fan-in of the destination,
                       distinct peers — the patterns a scan or DDoS leaves
  * summary            a deterministic one-paragraph explanation built from the
                       above (no language model involved)

Gradient × input is a local, first-order attribution: it says what the model's
output is most sensitive to around this input, not a causal proof.
"""
from __future__ import annotations

import numpy as np
import torch

PRETTY = {
    "dst_port": "destination port", "protocol": "protocol", "flow_duration": "flow duration (µs)",
    "total_fwd_packet": "forward packets", "total_bwd_packets": "backward packets",
    "syn_flag_count": "SYN flags", "rst_flag_count": "RST flags", "fin_flag_count": "FIN flags",
    "flow_bytes_per_s": "bytes/s", "flow_packets_per_s": "packets/s",
}


def pretty(name: str) -> str:
    return PRETTY.get(name, name.replace("_", " "))


def explain_edge(learner, g, edge: int, feature_names: list[str], scaler=None, top_k: int = 6) -> dict:
    model = learner.model
    model.eval()
    dev = learner.device
    x = g.x.to(dev)
    ei = g.edge_index.to(dev)
    ea = g.edge_attr.to(dev).clone().requires_grad_(True)
    if learner.family == "gnn":
        logits = model(x, ei, ea)
    else:
        logits = model(ea)
    probs = torch.softmax(logits[edge], dim=-1)
    pred = int(probs.argmax())
    logits[edge, pred].backward()
    grad = ea.grad.detach().cpu().numpy()
    attr = grad * ea.detach().cpu().numpy()                    # gradient × input
    own = attr[edge]
    order = np.argsort(-np.abs(own))[:top_k]
    raw = scaler.inverse_transform(g.edge_attr[edge:edge + 1].numpy())[0] if scaler is not None else None
    if raw is not None:
        raw = np.where(np.abs(raw) < 1e-6, 0.0, raw)            # float noise around a true zero
    features = [{"feature": feature_names[j], "label": pretty(feature_names[j]),
                 "attribution": float(own[j]), "value": float(raw[j]) if raw is not None else None,
                 "direction": "towards" if own[j] > 0 else "against"} for j in order]

    src, dst = g.edge_index.numpy()
    s, d = int(src[edge]), int(dst[edge])
    fan_out = int((src == s).sum()); fan_in = int((dst == d).sum())
    peers_out = int(len(np.unique(dst[src == s]))); peers_in = int(len(np.unique(src[dst == d])))
    ports = None
    if scaler is not None and "dst_port" in feature_names:  # distinct target ports: the port-scan signature
        j = feature_names.index("dst_port")
        col = g.edge_attr[src == s][:, j:j + 1].numpy()
        z = np.zeros((len(col), len(feature_names)))
        z[:, j] = col[:, 0]
        ports = int(len(np.unique(np.round(scaler.inverse_transform(z)[:, j]))))
    context = []
    if learner.family == "gnn":
        per_flow = np.abs(attr).sum(axis=1)
        per_flow[edge] = 0.0
        total = per_flow.sum() + np.abs(own).sum()
        for j in np.argsort(-per_flow)[:top_k]:
            if per_flow[j] <= 0:
                break
            context.append({"edge": int(j), "share": float(per_flow[j] / total) if total else 0.0,
                            "same_source": bool(src[j] == s), "same_destination": bool(dst[j] == d)})
        context_share = float(per_flow.sum() / total) if total else 0.0
    else:
        context_share = 0.0
    return {"edge": int(edge), "predicted_class": pred, "confidence": float(probs[pred].detach()),
            "features": features, "context": context, "context_share": context_share,
            "structure": {"source_host": s, "destination_host": d, "source_flows": fan_out,
                          "source_distinct_peers": peers_out, "destination_flows": fan_in,
                          "destination_distinct_peers": peers_in, "source_distinct_ports": ports,
                          "window_hosts": int(g.num_nodes)}}


def summarize(exp: dict, class_names: list[str]) -> str:
    c = class_names[exp["predicted_class"]]
    st = exp["structure"]
    parts = [f"Flagged as {c} with {exp['confidence'] * 100:.0f}% confidence."]
    if st["source_distinct_peers"] >= 20:
        parts.append(f"The source host contacted {st['source_distinct_peers']} different hosts in this window "
                     f"({st['source_flows']} flows) — a fan-out pattern typical of scanning.")
    if st["destination_distinct_peers"] >= 20:
        parts.append(f"The destination received flows from {st['destination_distinct_peers']} different hosts "
                     f"— a fan-in pattern typical of (distributed) flooding.")
    ports = st.get("source_distinct_ports")
    if ports is not None and ports >= 20:
        parts.append(f"The source probed {ports} different destination ports "
                     f"({st['source_flows']} flows) — a port-scan pattern.")
    elif st["source_flows"] >= 50 and st["source_distinct_peers"] < 5:
        parts.append(f"The source sent {st['source_flows']} flows to only {st['source_distinct_peers']} host(s) "
                     f"— repeated attempts against one target (e.g. brute force or DoS).")
    top = [f for f in exp["features"] if f["direction"] == "towards"][:3]
    if top:
        parts.append("Strongest evidence from the flow itself: " + ", ".join(
            f"{f['label']} = {f['value']:.4g}" if f["value"] is not None else f["label"] for f in top) + ".")
    if exp["context"]:
        parts.append(f"{exp['context_share'] * 100:.0f}% of the attribution came from {len(exp['context'])}+ "
                     f"neighbouring flows, i.e. the graph context mattered.")
    return " ".join(parts)
