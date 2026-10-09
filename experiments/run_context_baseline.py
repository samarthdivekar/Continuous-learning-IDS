"""Graph or host statistics? XGBoost with and without per-window host statistics (preliminary).

    python -m experiments.run_context_baseline --dataset cicids2017 --seeds 42 43 44
    python -m experiments.run_context_baseline --dataset cicids2017 --seeds 42 43 44 --loao

Joint (default): XGBoost is trained once on the training windows of ALL tasks and tested on the test windows of
all tasks (the interleaved split, the same windows and flows as results/<ds>/multiclass/continual/), in two
variants:
    xgb_flow       the flow's own features only
    xgb_flow_ctx   the flow's features + 12 host statistics of its window (src/preprocessing/context_features.py),
                   computed from the endpoints and destination port only, never from labels
It is compared with the gnn_joint and ffnn_joint rows of the interleaved continual table (same test flows).

--loao: binary leave-one-attack-out for both variants, the protocol of experiments/run_loao.py (train on the
training windows of every other task with stray held-out flows removed, test on the held-out task's test
windows); host statistics are computed on the graphs as the GNN saw them. Compared with
results/<ds>/binary/loao{,_seed43,_seed44}/.

Training settings are configs/default.yaml `xgboost` with the class weighting every XGBoost learner uses.
Nothing here changes an existing model or result; output goes to results/<ds>/multiclass/context_baseline/.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, data_config, results_dir
from experiments.run_loao import drop_category_edges
from src.evaluation.metrics import category_recall, core_metrics
from src.models.baseline_xgb import StaticXGBoost
from src.preprocessing.context_features import CONTEXT_FEATURES, window_context
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import class_weights
from src.utils.config import apply_overrides, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info

log = get_logger("context_baseline")
VARIANTS = ["xgb_flow", "xgb_flow_ctx"]
PORT_INDEX = 0          # dst_port is feature column 0 of every processed dataset (tests/test_host_context.py)


def window_arrays(g) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(flow features, flow features + host statistics, category) for one window graph."""
    x = g.edge_attr.numpy()
    src, dst = g.edge_index.numpy()
    ctx = window_context(src, dst, x[:, PORT_INDEX]).astype(np.float32)
    return x, np.concatenate([x, ctx], axis=1), g.y.numpy()


def stack(graphs: list) -> dict[str, np.ndarray]:
    parts = [window_arrays(g) for g in graphs]
    return {"xgb_flow": np.concatenate([p[0] for p in parts]),
            "xgb_flow_ctx": np.concatenate([p[1] for p in parts]),
            "y_cat": np.concatenate([p[2] for p in parts]).astype(np.int64)}


def fit_predict(cfg: dict, variant: str, train: dict, test: dict, n_classes: int, device: str) -> np.ndarray:
    y_tr = train["y_cat"] if cfg["label_mode"] == "multiclass" else (train["y_cat"] > 0).astype(np.int64)
    tcfg = cfg["train"]
    w = class_weights(y_tr, n_classes, tcfg["class_weight_power"], tcfg["class_weight_clip"]).numpy()
    model = StaticXGBoost(n_classes, cfg["xgboost"], seed=cfg["seed"], device=device, frozen=False)
    model.fit(train[variant], y_tr, sample_weight=w[y_tr])
    return model.predict(test[variant])


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def seed_summary(per_seed: pd.DataFrame, keys: list[str], metrics: list[str]) -> pd.DataFrame:
    g = per_seed.groupby(keys, sort=False)
    out = g[metrics].agg(["mean", "std"])
    out.columns = [f"{m}_{s}" for m, s in out.columns]
    out["n_seeds"] = g.size()
    for m in metrics:
        out[f"{m}_per_seed"] = g[m].apply(lambda s: " ".join(f"{v:.4f}" for v in s))
    return out.reset_index()


# ---------------------------------------------------------------------------------------------- joint
def run_joint(cfg_base: dict, args, data, out) -> None:
    cats = cfg_base["categories"]
    task_cats = data.task_categories
    train = stack([g for t in range(data.n_tasks) for g in data.graphs(t, "train")])
    test = stack([g for t in range(data.n_tasks) for g in data.graphs(t, "test")])
    log.info("joint: %d train flows, %d test flows, %d + %d features", len(train["y_cat"]), len(test["y_cat"]),
             train["xgb_flow"].shape[1], len(CONTEXT_FEATURES))
    rows = []
    for seed in args.seeds:
        cfg = apply_overrides(cfg_base, [f"seed={seed}"])
        for variant in VARIANTS:
            set_seed(seed)
            pred = fit_predict(cfg, variant, train, test, len(cats), args.xgb_device)
            m = core_metrics(test["y_cat"], pred, "multiclass")
            row = {"model": variant, "seed": seed, "macro_f1": m["macro_f1"], "accuracy": m["accuracy"],
                   "fpr": m["fpr"], "detection_rate": m["detection_rate"], "n_test_flows": m["n"]}
            for c in task_cats:
                row[f"recall_{c}"] = category_recall(test["y_cat"], pred, cats.index(c), "multiclass")
            rows.append(row)
            log.info("seed %d | %s | macro-F1 %.4f | FPR %.5f", seed, variant, m["macro_f1"], m["fpr"])
            pd.DataFrame(rows).to_csv(out / "joint_per_seed.csv", index=False)
    per_seed = pd.DataFrame(rows)
    metrics = ["macro_f1", "fpr"] + [f"recall_{c}" for c in task_cats]
    summary = seed_summary(per_seed, ["model"], metrics)
    summary.to_csv(out / "joint_summary.csv", index=False)

    # the existing joint-retraining references on the same test flows (interleaved continual table)
    ref_root = resolve_path(cfg_base, "results") / cfg_base["dataset"] / "multiclass" / "continual"
    ref_rows = []
    for seed in args.seeds:
        f = ref_root / f"seed{seed}" / "summary.csv"
        if not f.exists():
            continue
        df = pd.read_csv(f)
        if "ip_mode" in df:
            df = df[df["ip_mode"].fillna("none") == "none"]
        for model in ("gnn_joint", "ffnn_joint"):
            d = df[df["model"] == model]
            if d.empty:
                continue
            last = d[d["after_task"] == d["after_task"].max()].iloc[0]
            row = {"model": model, "seed": seed, "macro_f1": last["macro_f1_seen"], "fpr": last["fpr_seen"]}
            rm = ref_root / f"seed{seed}" / f"recall_matrix_{model}.csv"
            if rm.exists():
                r = pd.read_csv(rm, index_col=0).iloc[-1]
                for j, c in enumerate(task_cats):
                    row[f"recall_{c}"] = float(r.iloc[j])
            ref_rows.append(row)
    if ref_rows:
        ref = seed_summary(pd.DataFrame(ref_rows), ["model"], [m for m in metrics if m in ref_rows[0]])
        pd.concat([summary, ref], ignore_index=True).to_csv(out / "joint_comparison.csv", index=False)
    print(summary[["model", "n_seeds", "macro_f1_mean", "macro_f1_std", "fpr_mean"]].to_string(index=False))


# ----------------------------------------------------------------------------------------------- loao
def run_loao(cfg_base: dict, args, data, out) -> None:
    cfg_base = apply_overrides(cfg_base, ["label_mode=binary"])
    cats = cfg_base["categories"]
    rows = []
    for held_task, held_cat in enumerate(data.task_categories):
        cat_id = cats.index(held_cat)
        train = stack([drop_category_edges(g, cat_id)
                       for t in range(data.n_tasks) if t != held_task for g in data.graphs(t, "train")])
        test = stack(data.graphs(held_task, "test"))
        mask = test["y_cat"] == cat_id
        for seed in args.seeds:
            cfg = apply_overrides(cfg_base, [f"seed={seed}"])
            for variant in VARIANTS:
                set_seed(seed)
                pred = fit_predict(cfg, variant, train, test, 2, args.xgb_device)
                m = core_metrics((test["y_cat"] > 0).astype(np.int64), pred, "binary")
                rows.append({"held_out_category": held_cat, "model": variant, "seed": seed,
                             "n_heldout_flows": int(mask.sum()), "n_benign_flows": m["n_benign"],
                             "heldout_detection_rate": float((pred[mask] > 0).mean()) if mask.any() else np.nan,
                             "fpr": m["fpr"], "binary_f1": m["binary_f1"]})
                log.info("held-out %s | seed %d | %s | detection %.4f | fpr %.5f", held_cat, seed, variant,
                         rows[-1]["heldout_detection_rate"], m["fpr"])
                pd.DataFrame(rows).to_csv(out / "loao_binary_per_seed.csv", index=False)
    per_seed = pd.DataFrame(rows)
    seed_summary(per_seed, ["held_out_category", "model"], ["heldout_detection_rate", "fpr"]) \
        .to_csv(out / "loao_binary_summary.csv", index=False)
    print(per_seed.pivot_table(index="held_out_category", columns=["model", "seed"],
                               values="heldout_detection_rate").round(4).to_string())


def main():
    p = base_parser(__doc__)
    p.add_argument("--seeds", nargs="*", type=int, default=[42, 43, 44])
    p.add_argument("--loao", action="store_true", help="binary leave-one-attack-out instead of joint multiclass")
    p.add_argument("--out-name", default="context_baseline")
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    if cfg["split"].get("strategy", "interleaved") != "interleaved":
        raise SystemExit("this baseline is defined on the interleaved split only")
    cfg = apply_overrides(cfg, ["label_mode=multiclass"])
    args.xgb_device = "cuda" if get_device(cfg["train"]["device"]).type == "cuda" else "cpu"
    prepare_dataset(data_config(cfg))
    data = load_processed(data_config(cfg))
    out = results_dir(cfg, args, args.out_name)
    out.mkdir(parents=True, exist_ok=True)
    meta_path = data.root / "meta.json"
    write_run_info(out / ("run_info_loao.json" if args.loao else "run_info.json"), cfg, {
        "seeds": args.seeds,
        "protocol": ("binary leave-one-attack-out, as experiments/run_loao.py" if args.loao else
                     "joint: one fit on the training windows of all tasks, tested on the test windows of all tasks"),
        "variants": VARIANTS, "context_features": CONTEXT_FEATURES, "xgb_device": args.xgb_device,
        "status": "preliminary",
        "task_categories": data.task_categories,
        "data_meta": {k: data.meta.get(k) for k in ("n_flows", "n_windows", "n_features", "cache_key")},
        "data_hash": {"meta.json_sha256": file_sha256(meta_path),
                      "flows.parquet_sha256": file_sha256(data.root / "flows.parquet")},
    })
    (run_loao if args.loao else run_joint)(cfg, args, data, out)


if __name__ == "__main__":
    main()
