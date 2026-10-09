"""Cross-dataset generalisation: train on one dataset's task sequence, test on the other dataset's windows.

    python -m experiments.run_cross_dataset --train cicids2017 --test csecicids2018 --seeds 42 43 44

Both datasets are CICFlowMeter output with the same 83 features and the same category list, captured on
different networks a year apart. Every model is trained through the TRAIN dataset's full task sequence exactly
as in run_continual (validation selections applied), then scored, unchanged, on

  * the train dataset's own held-out test windows (in-distribution reference), and
  * the test dataset's held-out test windows, re-expressed in the train dataset's feature scale (each dataset is
    standardised with a scaler fitted on its own task-1 training flows; 2018 values are inverted to raw units
    and re-scaled with the 2017 scaler, as the live path does with sensor flows).

The re-scaling is exact except where a value falls outside the train dataset's clip range (±10 standard
deviations): measured for 2018 into 2017's scale, 0.7 % of feature values are clipped, exactly what a 2017-trained
deployment would do to such traffic. Nothing from the test dataset is used for training, tuning or scaling. Reports per seed and model: macro-F1
over the categories present, attack-vs-benign detection rate and false-positive rate, and recall per category.
Writes results/cross_dataset/<train>_to_<test>/{per_seed.csv, summary.csv, per_category.csv, run_info.json}.
"""
from __future__ import annotations

import argparse
import copy

import numpy as np
import pandas as pd
import torch

from experiments.common import ROOT  # noqa: F401  (puts the repository on sys.path)
from src.evaluation.continual import predict_graphs
from src.evaluation.metrics import category_recall, core_metrics
from src.preprocessing.pipeline import load_processed, prepare_dataset, processed_dir
from src.preprocessing.scaling import FeatureScaler
from src.training.learners import make_learner
from src.utils.config import REPO_ROOT, load_config, num_classes
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info
from src.utils.selection import apply_selection

log = get_logger("cross_dataset")
DEFAULT_MODELS = ["gnn_ewc_replay", "ffnn_ewc_replay", "ffnn_ctx_ewc_replay", "xgboost_replay", "gnn_joint"]


def rescaled_test_graphs(src_data, src_scaler: FeatureScaler, dst_scaler: FeatureScaler) -> list:
    """The source dataset's test windows with features moved into the destination dataset's scale."""
    out = []
    for t in range(src_data.n_tasks):
        for g in src_data.graphs(t, "test"):
            h = copy.copy(g)
            raw = src_scaler.inverse_transform(g.edge_attr.numpy())
            h.edge_attr = torch.from_numpy(dst_scaler.transform(raw))
            out.append(h)
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--train", default="cicids2017", choices=["cicids2017", "csecicids2018"])
    p.add_argument("--test", default="csecicids2018", choices=["cicids2017", "csecicids2018"])
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    p.add_argument("--seeds", nargs="*", type=int, default=[42, 43, 44])
    args = p.parse_args()
    out = REPO_ROOT / "results" / "cross_dataset" / f"{args.train}_to_{args.test}"
    out.mkdir(parents=True, exist_ok=True)

    tr_cfg0 = apply_selection(load_config(args.train, ["label_mode=multiclass"]), False, ["label_mode=multiclass"])
    te_cfg = load_config(args.test, ["label_mode=multiclass"])
    prepare_dataset(tr_cfg0)
    prepare_dataset(te_cfg)
    te_data = load_processed(te_cfg)
    tr_scaler = FeatureScaler.load(processed_dir(tr_cfg0) / "scaler.json")
    te_scaler = FeatureScaler.load(processed_dir(te_cfg) / "scaler.json")
    assert tr_scaler.columns == te_scaler.columns, "the two datasets must have the same features in the same order"
    cross = rescaled_test_graphs(te_data, te_scaler, tr_scaler)
    cats = tr_cfg0["categories"]
    log.info("%d %s test windows re-scaled into %s's feature scale", len(cross), args.test, args.train)

    rows, cat_rows = [], []
    for seed in args.seeds:
        ov = ["label_mode=multiclass", f"seed={seed}"]
        cfg = apply_selection(load_config(args.train, ov), False, ov)
        data = load_processed(cfg)
        device = get_device(cfg["train"]["device"])
        own = [g for t in range(data.n_tasks) for g in data.graphs(t, "test")]
        node_in = data.graphs(0, "train")[0].x.shape[1]
        for name in args.models:
            set_seed(seed)
            learner = make_learner(name, cfg, data.meta["n_features"], num_classes(cfg), device, node_in=node_in)
            for t in range(data.n_tasks):
                learner.learn(data.graphs(t, "train"), tag=f"task{t}")
            for where, graphs in ((args.train, own), (args.test, cross)):
                pr = predict_graphs(learner, graphs, "multiclass")
                m = core_metrics(pr["y_true"], pr["y_pred"], "multiclass")
                rows.append({"seed": seed, "model": name, "tested_on": where, **m})
                for c in np.unique(pr["y_cat"]):
                    if c == 0:
                        continue
                    cat_rows.append({"seed": seed, "model": name, "tested_on": where, "category": cats[c],
                                     "flows": int((pr["y_cat"] == c).sum()),
                                     "recall_exact": category_recall(pr["y_cat"], pr["y_pred"], int(c), "multiclass"),
                                     "detected_as_any_attack": float((pr["y_pred"][pr["y_cat"] == c] > 0).mean())})
                log.info("seed %d %-22s on %-14s macro-F1 %.3f  detection %.3f  FPR %.4f", seed, name, where,
                         m["macro_f1"], m["detection_rate"], m["fpr"])
            pd.DataFrame(rows).to_csv(out / "per_seed.csv", index=False)
            pd.DataFrame(cat_rows).to_csv(out / "per_category.csv", index=False)

    df = pd.DataFrame(rows)
    keys = ["macro_f1", "detection_rate", "fpr", "accuracy"]
    summary = df.groupby(["model", "tested_on"])[keys].agg(["mean", "std", "count"])
    summary.columns = [f"{a}_{b}" for a, b in summary.columns]
    summary.reset_index().to_csv(out / "summary.csv", index=False)
    write_run_info(out / "run_info.json", tr_cfg0, extra={"train": args.train, "test": args.test, "seeds": args.seeds,
                                         "models": args.models})
    log.info("wrote %s", out)


if __name__ == "__main__":
    main()
