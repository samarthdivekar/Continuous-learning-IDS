"""Regenerate every figure in results/ from the CSVs (never from memory).

    python -m experiments.make_plots --dataset cicids2017 --label-mode multiclass
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from experiments.common import base_parser, config_from_args, results_dir  # noqa: E402

# Fixed model -> colour assignment (colour follows the entity, never its rank).
# Validated categorical palette, light mode, slot order preserved.
MODEL_COLORS = {
    "gnn_ewc_replay": "#2a78d6",   # ours
    "gnn_naive": "#eb6834",
    "xgboost_static": "#1baf7a",
    "ffnn_ewc_replay": "#eda100",
    "ffnn_naive": "#e87ba4",
    "gnn_ewc": "#008300",
    "gnn_replay": "#4a3aa7",
    "gnn_joint": "#e34948",
    "ffnn_joint": "#898781",       # 9th series: neutral + dashed, reference only
}
MODEL_LABELS = {
    "gnn_ewc_replay": "GNN + EWC + replay (ours)", "gnn_naive": "GNN naive retrain",
    "xgboost_static": "XGBoost static", "ffnn_ewc_replay": "FFNN + EWC + replay",
    "ffnn_naive": "FFNN naive", "gnn_ewc": "GNN + EWC only", "gnn_replay": "GNN + replay only",
    "gnn_joint": "GNN joint (upper bound)", "ffnn_joint": "FFNN joint (upper bound)",
}
HEADLINE = ["gnn_ewc_replay", "gnn_naive", "xgboost_static", "ffnn_ewc_replay"]
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 11,
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": "#52514e", "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
    "legend.frameon": False, "savefig.dpi": 160, "savefig.bbox": "tight",
})


def _style(model):
    dashed = model.endswith("_joint")
    return dict(color=MODEL_COLORS.get(model, MUTED), linewidth=2, marker="o", markersize=6,
                linestyle="--" if dashed else "-", label=MODEL_LABELS.get(model, model))


def plot_continual(cdir: Path, models: list[str]) -> None:
    s = pd.read_csv(cdir / "summary.csv")
    if "ip_mode" in s:
        s = s[s["ip_mode"] == "none"]
    models = [m for m in models if m in set(s["model"])]
    cats = s.drop_duplicates("after_task").sort_values("after_task")["task_category"].tolist()
    panels = [("accuracy_seen", "Accuracy (tasks seen so far)"),
              ("macro_f1_seen", "Macro-F1 (tasks seen so far)"),
              ("retention_rate", f"Retention: recall on task-1 {cats[0]}"),
              ("fpr_seen", "False-positive rate (benign flagged)")]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5), sharex=True)
    for ax, (col, title) in zip(axes.flat, panels):
        for m in models:
            d = s[s["model"] == m].sort_values("after_task")
            ax.plot(d["after_task"], d[col], **_style(m))
        ax.set_title(title, loc="left", color=INK, fontsize=12)
        ax.set_xticks(range(len(cats)))
        ax.set_xticklabels([f"{i + 1}\n{c}" for i, c in enumerate(cats)], fontsize=9)
        if col != "fpr_seen":
            ax.set_ylim(-0.02, 1.02)
    axes[1, 0].set_xlabel("after training task")
    axes[1, 1].set_xlabel("after training task")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=min(4, len(models)), bbox_to_anchor=(0.5, 1.03))
    fig.savefig(cdir / "continual_metrics.png")
    plt.close(fig)

    for m in models:
        f = cdir / f"recall_matrix_{m}.csv"
        if not f.exists():
            continue
        R = pd.read_csv(f, index_col=0)
        fig, ax = plt.subplots(figsize=(7.5, 5.5))
        im = ax.imshow(R.to_numpy(dtype=float), cmap="Blues", vmin=0, vmax=1)
        ax.grid(False)
        ax.set_xticks(range(R.shape[1]))
        ax.set_xticklabels([c.split("_", 1)[1] for c in R.columns], rotation=35, ha="right")
        ax.set_yticks(range(R.shape[0]))
        ax.set_yticklabels([f"after {i + 1}" for i in range(R.shape[0])])
        for i in range(R.shape[0]):
            for j in range(R.shape[1]):
                v = R.iat[i, j]
                if np.isfinite(v):
                    ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                            color="#ffffff" if v > 0.6 else INK)
        ax.set_title(f"{MODEL_LABELS.get(m, m)}: per-category recall", loc="left", color=INK)
        ax.set_xlabel("evaluated on category (test windows)")
        fig.colorbar(im, ax=ax, fraction=0.04)
        fig.savefig(cdir / f"recall_matrix_{m}.png")
        plt.close(fig)


def plot_drift(ddir: Path) -> None:
    w = pd.read_csv(ddir / "stream_windows.csv")
    e = pd.read_csv(ddir / "stream_eval.csv")
    runs = w[["model", "policy"]].drop_duplicates().values.tolist()
    fig, axes = plt.subplots(len(runs), 1, figsize=(13, 2.2 * len(runs)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, (m, pol) in zip(axes, runs):
        d = w[(w["model"] == m) & (w["policy"] == pol)]
        ax.plot(d["stream_index"], d["error_rate"], color=MODEL_COLORS.get(m, MUTED), linewidth=1.5)
        ax.fill_between(d["stream_index"], 0, d["true_attack_fraction"], color=GRID, step="mid",
                        label="attack share of window")
        for x in d.loc[d["retrained"], "stream_index"]:
            ax.axvline(x, color=INK, linewidth=1, linestyle=":")
        bounds = d.loc[d["task_id"].diff().fillna(0) != 0, "stream_index"]
        for x in bounds:
            ax.axvline(x, color=MUTED, linewidth=0.8)
        ax.set_ylim(0, 1)
        ax.set_title(f"{MODEL_LABELS.get(m, m)} | policy={pol} | retrains={int(d['retrained'].sum())}",
                     loc="left", fontsize=10, color=INK)
        ax.set_ylabel("window error")
    axes[-1].set_xlabel("stream window (dotted = adaptation, grey = true task boundary, shaded = attack share)")
    fig.savefig(ddir / "drift_timeline.png")
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2), sharex=True)
    for ax, col, title in zip(axes, ["accuracy_seen", "retention_rate", "fpr_seen"],
                              ["Accuracy (seen tasks)", "Retention (task-1 category)", "FPR"]):
        for m, pol in runs:
            d = e[(e["model"] == m) & (e["policy"] == pol)]
            ls = ["-", "--", ":", "-."][["adwin", "periodic", "oracle", "never"].index(pol)]
            ax.plot(d["stream_index"], d[col], color=MODEL_COLORS.get(m, MUTED), linestyle=ls, linewidth=2,
                    label=f"{MODEL_LABELS.get(m, m)} / {pol}")
        ax.set_title(title, loc="left", color=INK)
        ax.set_xlabel("stream window")
    axes[0].legend(fontsize=8, loc="lower left")
    fig.savefig(ddir / "drift_metrics.png")
    plt.close(fig)


def plot_loao(ldir: Path) -> None:
    df = pd.read_csv(ldir / "loao.csv")
    piv = df.pivot_table(index="held_out_category", columns="model", values="heldout_detection_rate")
    models = [m for m in MODEL_COLORS if m in piv.columns]
    # trained once, jointly on all other tasks -> not the continual strategies of those names
    loao_label = {"xgboost_static": "XGBoost", "gnn_naive": "GNN (graph)", "ffnn_naive": "FFNN (per-flow)"}
    fig, ax = plt.subplots(figsize=(12, 4.5))
    width = 0.8 / len(models)
    x = np.arange(len(piv))
    for i, m in enumerate(models):
        ax.bar(x + i * width, piv[m].to_numpy(), width - 0.02, color=MODEL_COLORS[m], label=loao_label.get(m, MODEL_LABELS.get(m, m)))
    ax.set_xticks(x + width * (len(models) - 1) / 2)
    ax.set_xticklabels(piv.index)
    ax.set_ylim(0, 1)
    ax.set_ylabel("detection rate on unseen category")
    ax.legend(ncol=len(models), loc="upper center", bbox_to_anchor=(0.5, 1.15))
    fig.savefig(ldir / "loao.png")
    plt.close(fig)


def main():
    p = base_parser(__doc__)
    args = p.parse_args()
    cfg = config_from_args(args)
    base = results_dir(cfg, args)
    if (base / "continual" / "summary.csv").exists():
        plot_continual(base / "continual", list(MODEL_COLORS))
        # headline-only version for slides
        (base / "continual" / "headline").mkdir(exist_ok=True)
        s = pd.read_csv(base / "continual" / "summary.csv")
        s[s["model"].isin(HEADLINE)].to_csv(base / "continual" / "headline" / "summary.csv", index=False)
        plot_continual(base / "continual" / "headline", HEADLINE)
    if (base / "drift" / "stream_windows.csv").exists():
        plot_drift(base / "drift")
    if (base / "loao" / "loao.csv").exists():
        plot_loao(base / "loao")
    print("plots written under", base)


if __name__ == "__main__":
    main()
