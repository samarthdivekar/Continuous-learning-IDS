"""Preliminary host-context baseline (review RQ1: does the graph help, or would host statistics do?).

    python -m experiments.run_context_baseline --dataset cicids2017 --seeds 42 43 44            # joint, multiclass
    python -m experiments.run_context_baseline --dataset cicids2017 --seeds 42 43 44 --loao     # + binary LOAO

XGBoost (the `xgboost` settings in configs/default.yaml, class weights as for the other models) on
  (a) flow   — the 83 flow features only, and
  (b) ctx    — the same plus 12 per-window host-context features (src/preprocessing/context_features.py:
               out/in-degree, distinct destinations / sources / destination ports, flows per host pair, each
               also divided by the window's flow count), computed from endpoints and ports only, never labels.

Joint: trained once on the training windows of ALL tasks, scored on the test windows of all tasks, on the
interleaved split — the same cached windows, splits and test flows as the headline task-sequence table — and
set beside its `gnn_joint` and `ffnn_joint` rows. LOAO (binary): the protocol of experiments/run_loao.py (train
on every other task with stray held-out flows removed, test on the held-out task's test windows), so the rows
sit beside results/<dataset>/binary/loao_seeds/.

Writes results/<dataset>/multiclass/context_baseline/{per_seed.csv, per_category.csv, summary.csv,
comparison.csv, run_info.json} and, with --loao, results/<dataset>/binary/context_baseline_loao/.
Preliminary: joint training only (no continual learning), three seeds. Nothing existing is modified.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd
import torch

from experiments.common import ROOT  # noqa: F401  (puts the repository on sys.path)
from experiments.common import data_config
from experiments.run_loao import drop_category_edges
from src.evaluation.metrics import category_recall, core_metrics
from src.models.baseline_xgb import StaticXGBoost
from src.preprocessing.context_features import CONTEXT_NAMES, graph_context
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import class_weights
from src.utils.config import REPO_ROOT, load_config, num_classes
from src.utils.logging import get_logger
from src.utils.repro import write_run_info

log = get_logger("context_baseline")
VARIANTS = ("flow", "ctx")


def matrix(graphs: list, variant: str) -> tuple[np.ndarray, np.ndarray]:
    """Feature matrix and category labels of every flow in `graphs`."""
    X, y = [], []
    for g in graphs:
        x = g.edge_attr.numpy()
        X.append(np.concatenate([x, graph_context(g)], 1) if variant == "ctx" else x)
        y.append(g.y.numpy())
    return np.concatenate(X).astype(np.float32), np.concatenate(y).astype(np.int64)


def fit(X, y, n_cls, cfg, seed, device) -> StaticXGBoost:
    t = cfg["train"]
    w = class_weights(y, n_cls, t["class_weight_power"], t["class_weight_clip"]).numpy()
    m = StaticXGBoost(n_cls, cfg["xgboost"], seed=seed, device=device, frozen=False)
    m.fit(X, y, sample_weight=w[y])
    return m


def run_joint(args, cfg0, data, device, out):
    cats = cfg0["categories"]
    n_cls = num_classes(cfg0)
    train = [g for t in range(data.n_tasks) for g in data.graphs(t, "train")]
    test = [g for t in range(data.n_tasks) for g in data.graphs(t, "test")]
    mats = {v: (matrix(train, v), matrix(test, v)) for v in VARIANTS}
    log.info("joint: %d train flows, %d test flows", len(mats["flow"][0][1]), len(mats["flow"][1][1]))
    rows, cat_rows = [], []
    for seed in args.seeds:
        for v in VARIANTS:
            (Xtr, ytr), (Xte, yte) = mats[v]
            t0 = time.time()
            m = fit(Xtr, ytr, n_cls, cfg0, seed, device)
            pred = m.predict(Xte)
            met = core_metrics(yte, pred, "multiclass")
            rows.append({"seed": seed, "model": f"xgboost_joint_{v}", "n_features": Xtr.shape[1],
                         "macro_f1_seen": met["macro_f1"], "fpr_seen": met["fpr"],
                         "detection_rate_seen": met["detection_rate"], "accuracy_seen": met["accuracy"],
                         "train_seconds": time.time() - t0})
            for c in np.unique(yte):
                if c == 0:
                    continue
                cat_rows.append({"seed": seed, "model": f"xgboost_joint_{v}", "category": cats[c],
                                 "test_flows": int((yte == c).sum()),
                                 "recall": category_recall(yte, pred, int(c), "multiclass")})
            log.info("seed %d %-5s macro-F1 %.4f FPR %.5f (%.0f s)", seed, v, met["macro_f1"], met["fpr"],
                     rows[-1]["train_seconds"])
            pd.DataFrame(rows).to_csv(out / "per_seed.csv", index=False)
            pd.DataFrame(cat_rows).to_csv(out / "per_category.csv", index=False)
    df = pd.DataFrame(rows)
    keys = ["macro_f1_seen", "fpr_seen", "detection_rate_seen", "accuracy_seen"]
    summ = df.groupby("model")[keys].agg(["mean", "std", "count"])
    summ.columns = [f"{a}_{b}" for a, b in summ.columns]
    summ.reset_index().to_csv(out / "summary.csv", index=False)

    # beside the headline table's joint references (same windows, same test flows, final task)
    head = REPO_ROOT / "results" / args.dataset / "multiclass" / "continual" / "summary_all_seeds.csv"
    ref = pd.read_csv(head)
    ref = ref[(ref["after_task"] == ref["after_task"].max()) & (ref["ip_mode"] == "none")
              & ref["model"].isin(["gnn_joint", "ffnn_joint", "gnn_ewc_replay", "ffnn_ewc_replay", "xgboost_static"])
              & ref["seed"].isin(args.seeds)]
    both = pd.concat([ref[["seed", "model", "macro_f1_seen", "fpr_seen"]].assign(source=str(head.relative_to(REPO_ROOT))),
                      df[["seed", "model", "macro_f1_seen", "fpr_seen"]].assign(source="this run")])
    cmp_ = both.groupby(["model", "source"])[["macro_f1_seen", "fpr_seen"]].agg(["mean", "std", "count"])
    cmp_.columns = [f"{a}_{b}" for a, b in cmp_.columns]
    cmp_.reset_index().sort_values("macro_f1_seen_mean", ascending=False).to_csv(out / "comparison.csv", index=False)
    print(cmp_.round(4).to_string())


def run_loao(args, data_cfg, data, device, out):
    cfg = load_config(args.dataset, ["label_mode=binary"])
    cats = cfg["categories"]
    rows = []
    for held_task, held_cat in enumerate(data.task_categories):
        cat_id = cats.index(held_cat)
        train = [drop_category_edges(g, cat_id)
                 for t in range(data.n_tasks) if t != held_task for g in data.graphs(t, "train")]
        test = data.graphs(held_task, "test")
        for v in VARIANTS:
            Xtr, ctr = matrix(train, v)
            Xte, cte = matrix(test, v)
            ytr, yte = (ctr > 0).astype(np.int64), (cte > 0).astype(np.int64)
            for seed in args.seeds:
                m = fit(Xtr, ytr, 2, cfg, seed, device)
                pred = m.predict(Xte)
                met = core_metrics(yte, pred, "binary")
                mask = cte == cat_id
                rows.append({"held_out_category": held_cat, "model": f"xgboost_{v}", "seed": seed,
                             "n_heldout_flows": int(mask.sum()), "n_benign_flows": int((cte == 0).sum()),
                             "heldout_detection_rate": float((pred[mask] > 0).mean()) if mask.any() else np.nan,
                             "fpr": met["fpr"], "binary_f1": met.get("binary_f1", np.nan)})
                log.info("LOAO %-12s %-4s seed %d detection %.4f FPR %.5f", held_cat, v, seed,
                         rows[-1]["heldout_detection_rate"], met["fpr"])
                pd.DataFrame(rows).to_csv(out / "per_seed.csv", index=False)
    df = pd.DataFrame(rows)
    s = df.groupby(["held_out_category", "model"])[["heldout_detection_rate", "fpr"]].agg(["mean", "std", "min", "max"])
    s.columns = [f"{a}_{b}" for a, b in s.columns]
    s.reset_index().to_csv(out / "summary.csv", index=False)
    print(df.pivot_table(index="held_out_category", columns=["model", "seed"], values="heldout_detection_rate").round(4).to_string())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="cicids2017", choices=["cicids2017", "csecicids2018"])
    p.add_argument("--seeds", nargs="*", type=int, default=[42, 43, 44])
    p.add_argument("--loao", action="store_true", help="also run binary leave-one-attack-out")
    p.add_argument("--skip-joint", action="store_true")
    args = p.parse_args()
    cfg0 = load_config(args.dataset, ["label_mode=multiclass"])
    dcfg = data_config(cfg0)
    prepare_dataset(dcfg)
    data = load_processed(dcfg)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    extra = {"seeds": args.seeds, "variants": list(VARIANTS), "context_features": CONTEXT_NAMES,
             "command": " ".join(sys.argv), "status": "preliminary: joint training only, 3 seeds",
             "data_cache": str(data.root) if hasattr(data, "root") else None}
    if not args.skip_joint:
        out = REPO_ROOT / "results" / args.dataset / "multiclass" / "context_baseline"
        out.mkdir(parents=True, exist_ok=True)
        write_run_info(out / "run_info.json", cfg0, extra)
        run_joint(args, cfg0, data, device, out)
    if args.loao:
        out = REPO_ROOT / "results" / args.dataset / "binary" / "context_baseline_loao"
        out.mkdir(parents=True, exist_ok=True)
        write_run_info(out / "run_info.json", cfg0, {**extra, "protocol": "experiments/run_loao.py, binary"})
        run_loao(args, dcfg, data, device, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
