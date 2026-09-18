"""Build results/RESULTS.md from the result CSVs (no number is typed by hand).

    python -m experiments.make_report
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.utils.config import REPO_ROOT

RES = REPO_ROOT / "results"
LABELS = {
    "xgboost_static": "XGBoost static", "gnn_naive": "GNN naive retrain",
    "gnn_ewc_replay": "**GNN + EWC + replay (ours)**", "ffnn_ewc_replay": "FFNN + EWC + replay (ablation)",
    "ffnn_naive": "FFNN naive retrain", "gnn_ewc": "GNN + EWC only", "gnn_replay": "GNN + replay only",
    "gnn_joint": "GNN joint retrain (upper bound, not continual)",
    "ffnn_joint": "FFNN joint retrain (upper bound, not continual)",
}
ORDER = list(LABELS)


def fmt(m, s=None, pct=False, digits=3):
    if m is None or (isinstance(m, float) and np.isnan(m)):
        return "–"
    if pct:
        v = f"{m * 100:.{digits - 1}f}%"
        return v if s is None or np.isnan(s) else f"{v} ± {s * 100:.{digits - 1}f}"
    v = f"{m:.{digits}f}"
    return v if s is None or np.isnan(s) else f"{v} ± {s:.{digits}f}"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


def ewc_settings(ds: str, mode: str) -> dict:
    """Validation-selected λ/γ per model (fallback for runs made before the
    summary carried the columns; the two always agree when both are present)."""
    for m in (mode, "multiclass"):
        f = RES / ds / m / "ewc_lambda_sweep" / "selected.json"
        if f.exists():
            return json.loads(f.read_text())   # exact model names only
    return {}


def continual_section(ds: str, mode: str) -> list[str]:
    d = RES / ds / mode / "continual"
    if not (d / "summary.csv").exists():
        return []
    sel = ewc_settings(ds, mode)
    mean = pd.read_csv(d / "summary.csv")
    std = pd.read_csv(d / "summary_std.csv") if (d / "summary_std.csv").exists() else None
    seeds = json.loads((d / "seeds.json").read_text())["seeds"] if (d / "seeds.json").exists() else ["?"]
    last_t = mean["after_task"].max()
    out = [f"### {ds} — {mode} — task sequence (test split, mean ± std over seeds {seeds})", ""]
    rows = []
    for model in [m for m in ORDER if m in set(mean["model"])]:
        m = mean[(mean["model"] == model) & (mean["after_task"] == last_t)].iloc[0]
        s = std[(std["model"] == model) & (std["after_task"] == last_t)].iloc[0] if std is not None else {}
        forg = []
        for sd in seeds:
            f = d / f"seed{sd}" / f"forgetting_{model}.json"
            if f.exists():
                forg.append(json.loads(f.read_text()))
        bwt = np.mean([x["bwt"] for x in forg]) if forg else np.nan
        lam, gam = m.get("ewc_lambda", np.nan), m.get("ewc_gamma", np.nan)
        if (lam is None or (isinstance(lam, float) and np.isnan(lam))) and model in sel:
            lam, gam = sel[model]["lambda"], sel[model]["gamma"]
        rows.append({
            "Model": LABELS[model],
            "EWC λ / γ": "–" if lam is None or (isinstance(lam, float) and np.isnan(lam)) else f"{lam:g} / {gam:g}",
            "Accuracy (seen)": fmt(m["accuracy_seen"], s.get("accuracy_seen", np.nan)),
            "Macro-F1 (seen)": fmt(m["macro_f1_seen"], s.get("macro_f1_seen", np.nan)),
            "Retention (task-1 recall)": fmt(m["retention_rate"], s.get("retention_rate", np.nan)),
            "FPR": fmt(m["fpr_seen"], s.get("fpr_seen", np.nan), pct=True),
            "BWT (category recall)": fmt(bwt),
        })
    out += [md_table(pd.DataFrame(rows)), ""]
    cats = mean.drop_duplicates("after_task").sort_values("after_task")["task_category"].tolist()
    out += [f"Task order: {' → '.join(cats)}. Metrics after the final task; 'seen' = test windows of all tasks.", ""]

    # accuracy-over-time (macro-F1) for headline models
    head = [m for m in ["xgboost_static", "gnn_naive", "gnn_ewc_replay", "ffnn_ewc_replay"] if m in set(mean["model"])]
    for metric, title in [("macro_f1_seen", "Macro-F1 over time"), ("retention_rate", "Retention over time"),
                          ("fpr_seen", "FPR over time")]:
        piv = mean[mean["model"].isin(head)].pivot_table(index="model", columns="after_task", values=metric)
        tbl = pd.DataFrame({"Model": [LABELS[m] for m in head]})
        for t in piv.columns:
            tbl[f"after {int(t) + 1} ({cats[int(t)]})"] = [fmt(piv.loc[m, t], pct=metric == "fpr_seen") for m in head]
        out += [f"**{title}**", "", md_table(tbl), ""]
    return out


def drift_section(ds: str, mode: str) -> list[str]:
    f = RES / ds / mode / "drift" / "summary.csv"
    if not f.exists():
        return []
    s = pd.read_csv(f)
    tbl = pd.DataFrame({
        "Model": s["model"].map(lambda m: LABELS.get(m, m)), "Policy": s["policy"],
        "Stream windows": s["stream_windows"], "True task boundaries": s["true_task_boundaries"],
        "Drift flags": s["drift_flags"], "Retrains": s["retrains"],
        "Final accuracy": s["final_accuracy_seen"].map(fmt), "Final macro-F1": s["final_macro_f1_seen"].map(fmt),
        "Final retention": s["final_retention_rate"].map(fmt), "Final FPR": s["final_fpr_seen"].map(lambda v: fmt(v, pct=True)),
    })
    return [f"### {ds} — {mode} — drift-triggered adaptation (stream of tasks 2..T, seed 42)", "",
            md_table(tbl), ""]


def loao_section(ds: str, mode: str) -> list[str]:
    f = RES / ds / mode / "loao" / "loao.csv"
    if not f.exists():
        return []
    df = pd.read_csv(f)
    det = df.pivot_table(index="held_out_category", columns="model", values="heldout_detection_rate")
    fpr = df.pivot_table(index="held_out_category", columns="model", values="fpr")
    n = df.groupby("held_out_category")["n_heldout_flows"].first()
    models = [m for m in ORDER if m in det.columns]
    # each model is trained ONCE, jointly on all other tasks: continual-strategy names would mislead
    loao_label = {"xgboost_static": "XGBoost", "gnn_naive": "GNN (graph)", "ffnn_naive": "FFNN (per-flow)"}
    tbl = pd.DataFrame({"Held-out category": det.index, "Test flows": n.loc[det.index].values})
    for m in models:
        tbl[f"{loao_label.get(m, LABELS[m])} detection"] = [fmt(v) for v in det[m]]
        tbl[f"{loao_label.get(m, LABELS[m])} FPR"] = [fmt(v, pct=True) for v in fpr[m]]
    return [f"### {ds} — {mode} — leave-one-attack-out (joint training on the other tasks, seed 42)", "",
            md_table(tbl), ""]


def ipremap_section(ds: str, mode: str) -> list[str]:
    f = RES / ds / mode / "ip_remap" / "summary.csv"
    if not f.exists():
        return []
    s = pd.read_csv(f)
    last = s[s["after_task"] == s["after_task"].max()]
    rows = []
    for model in [m for m in ORDER if m in set(last["model"])]:
        r = {"Model": LABELS[model]}
        for ip in ["none", "permute", "random_src"]:
            x = last[(last["model"] == model) & (last["ip_mode"] == ip)]
            if len(x):
                r[f"{ip}: macro-F1"] = fmt(x["macro_f1_seen"].iloc[0])
                r[f"{ip}: FPR"] = fmt(x["fpr_seen"].iloc[0], pct=True)
        rows.append(r)
    return [f"### {ds} — {mode} — IP-remap evaluation (same trained model, seed 42)", "",
            md_table(pd.DataFrame(rows)), ""]


def tuning_section(ds: str) -> list[str]:
    out = []
    t = RES / ds / "multiclass" / "tuning" / "tuning.csv"
    if t.exists():
        df = pd.read_csv(t)
        df = df[["model", "overrides", "val_macro_f1_seen", "val_fpr_seen"]].copy()
        df["val_macro_f1_seen"] = df["val_macro_f1_seen"].map(fmt)
        df["val_fpr_seen"] = df["val_fpr_seen"].map(lambda v: fmt(v, pct=True))
        out += [f"### {ds} — validation tuning (epochs / replay loss)", "", md_table(df), ""]
    w = RES / ds / "multiclass" / "ewc_lambda_sweep" / "sweep.csv"
    if w.exists():
        df = pd.read_csv(w).sort_values(["model", "gamma", "lambda"])
        df = df[["model", "gamma", "lambda", "lr_times_lambda", "diverged", "val_macro_f1_seen",
                 "val_retention_rate", "val_fpr_seen", "max_stability_ratio"]].copy()
        for c in ["val_macro_f1_seen", "val_retention_rate", "max_stability_ratio"]:
            df[c] = df[c].map(fmt)
        df["val_fpr_seen"] = df["val_fpr_seen"].map(lambda v: fmt(v, pct=True))
        sel = (RES / ds / "multiclass" / "ewc_lambda_sweep" / "selected.json")
        out += [f"### {ds} — EWC λ / γ sweep (validation split)", "", md_table(df), "",
                f"Selected: `{json.dumps(json.loads(sel.read_text())) if sel.exists() else 'n/a'}`", ""]
    return out


def main():
    lines = ["# Results", "",
             "Generated by `python -m experiments.make_report` from the CSV files in this directory.",
             "Do not edit by hand — rerun the experiments and this script instead.", ""]
    for ds in ["cicids2017", "csecicids2018"]:
        if not (RES / ds).exists():
            continue
        lines += [f"## {ds}", ""]
        for mode in ["multiclass", "binary"]:
            lines += continual_section(ds, mode)
        lines += drift_section(ds, "multiclass")
        for mode in ["binary", "multiclass"]:
            lines += loao_section(ds, mode)
        lines += ipremap_section(ds, "multiclass")
        lines += tuning_section(ds)
    (RES / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote", RES / "RESULTS.md")


if __name__ == "__main__":
    main()
