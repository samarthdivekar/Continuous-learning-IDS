"""Open-set novelty detection on the task sequence (improvement 6).

    python -m experiments.run_open_set --dataset cicids2017

For every step i of the task sequence, the model checkpoint saved after task i
(by run_continual, first seed) is asked to flag the NEXT task's attack flows as
"novel" — an attack category it has never been trained on — while known
traffic (test windows of tasks 0..i) should not be flagged.

Protocol
  known classes after task i = Benign + categories of tasks 0..i
  threshold  : calibrated on VALIDATION flows of known classes (target 5 % false alarms)
  prototypes : class means of embeddings of TRAIN flows of known classes
  novel      : attack flows of task i+1's category in task i+1's TEST windows
  known test : all flows of known classes in test windows of tasks 0..i
  clusters   : flows of task i+1's test windows that are flagged, clustered
               (k by silhouette) — how pure is the proposed new category?
Outputs: results/<ds>/multiclass/open_set/{open_set.csv, clusters.csv, run_info.json}
"""
import numpy as np
import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.evaluation.open_set import METHODS, calibrate, detection_metrics, fit_prototypes, novelty_scores, propose_clusters
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import load_learner_checkpoint, make_learner
from src.utils.config import num_classes, resolve_path
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info

log = get_logger("open_set")
MODELS = ["gnn_ewc_replay", "ffnn_ewc_replay"]


def collect(learner, graphs, max_windows=None, rng=None):
    if max_windows and len(graphs) > max_windows:
        graphs = [graphs[i] for i in sorted(rng.choice(len(graphs), max_windows, replace=False))]
    L, Z, Y = [], [], []
    for g in graphs:
        lo, z = learner.predict_details(g)
        L.append(lo); Z.append(z); Y.append(g.y.numpy())
    if not L:
        return np.empty((0, 1)), np.empty((0, 1)), np.empty(0, int)
    return np.concatenate(L), np.concatenate(Z), np.concatenate(Y)


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=MODELS)
    p.add_argument("--target-fpr", type=float, default=0.05)
    p.add_argument("--max-train-windows", type=int, default=30)
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    if cfg["label_mode"] != "multiclass":
        raise SystemExit("open-set evaluation needs multiclass checkpoints")
    set_seed(cfg["seed"])
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "open_set")
    write_run_info(out / "run_info.json", cfg, {"models": args.models, "target_fpr": args.target_fpr,
                                                  "task_categories": data.task_categories})
    device = get_device(cfg["train"]["device"])
    ckpt = resolve_path(cfg, "checkpoints") / cfg["dataset"] / cfg["label_mode"]
    cats = cfg["categories"]
    task_cat = [cats.index(c) for c in data.task_categories]
    node_in = data.graphs(0, "train")[0].x.shape[1]
    rng = np.random.default_rng(cfg["seed"])
    rows, crow = [], []
    for model in args.models:
        for i in range(data.n_tasks - 1):
            f = ckpt / f"{model}_after_task{i}.pt"
            if not f.exists():
                log.warning("missing checkpoint %s — skipped", f)
                continue
            learner = load_learner_checkpoint(make_learner(model, cfg, data.meta["n_features"], num_classes(cfg),
                                                           device, node_in=node_in), f)
            known = [0] + task_cat[: i + 1]
            novel_cat = task_cat[i + 1]
            # prototypes from TRAIN flows of known classes
            tr = [g for t in range(i + 1) for g in data.graphs(t, "train")]
            _, ztr, ytr = collect(learner, tr, args.max_train_windows * (i + 1), rng)
            protos = fit_prototypes(ztr, ytr, known, seed=cfg["seed"])
            # threshold from VALIDATION flows of known classes
            lv, zv, yv = collect(learner, [g for t in range(i + 1) for g in data.graphs(t, "val")])
            kv = np.isin(yv, known)
            sv = novelty_scores(lv[kv], zv[kv], known, protos)
            # known test flows / novel flows of the next task
            lk, zk, yk = collect(learner, [g for t in range(i + 1) for g in data.graphs(t, "test")])
            kk = np.isin(yk, known)
            sk = novelty_scores(lk[kk], zk[kk], known, protos)
            ln, zn, yn = collect(learner, data.graphs(i + 1, "test"))
            sn_all = novelty_scores(ln, zn, known, protos)
            is_novel = yn == novel_cat
            for mth in METHODS:
                if mth not in sv:
                    continue
                thr = calibrate(sv[mth], args.target_fpr)
                m = detection_metrics(sk[mth], sn_all[mth][is_novel], thr)
                flagged_next = sn_all[mth] > thr
                m.update({"model": model, "after_task": i, "known_categories": ",".join(cats[c] for c in known),
                          "novel_category": cats[novel_cat], "method": mth, "threshold": thr,
                          "flag_precision_next_task": float(is_novel[flagged_next].mean()) if flagged_next.any() else float("nan"),
                          "flagged_next_task": int(flagged_next.sum())})
                rows.append(m)
                log.info("%s after %d | novel %s | %s AUROC %.3f TPR %.3f FPR %.3f", model, i, cats[novel_cat],
                         mth, m["auroc"], m["tpr"], m["fpr_known"])
                if mth == "prototype":
                    c = propose_clusters(zn[flagged_next], yn[flagged_next], seed=cfg["seed"])
                    c.update({"model": model, "after_task": i, "novel_category": cats[novel_cat],
                              "majority_category": cats[c["majority_category"]] if c.get("majority_category") is not None else None})
                    crow.append(c)
            pd.DataFrame(rows).to_csv(out / "open_set.csv", index=False)
            pd.DataFrame(crow).to_csv(out / "clusters.csv", index=False)
    df = pd.DataFrame(rows)
    print(df.pivot_table(index=["model", "method"], values=["auroc", "tpr", "fpr_known"], aggfunc="mean").round(3).to_string())


if __name__ == "__main__":
    main()
