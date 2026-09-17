"""Phase 8a: leave-one-attack-out generalisation.

    python -m experiments.run_loao --dataset cicids2017

For each attack category c:
  train (jointly, non-sequentially) on the training windows of every task
  except c's task, with any stray flows of category c removed from the
  remaining graphs; test on the test windows of c's task.
Reported: detection rate on the unseen category (flagged as ANY attack), FPR
on the benign flows of those windows, binary F1.
In multiclass mode a model cannot name an unseen class, so detection = "predicted
as some attack class"; binary mode is the natural setting for this test.
"""
import numpy as np
import pandas as pd
import torch
from torch_geometric.data import Data

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.evaluation.continual import predict_graphs
from src.evaluation.metrics import core_metrics
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.training.learners import make_learner
from src.utils.config import num_classes
from src.utils.logging import get_logger
from src.utils.repro import get_device, set_seed, write_run_info

log = get_logger("loao")
DEFAULT_MODELS = ["xgboost_static", "ffnn_naive", "gnn_naive"]


def drop_category_edges(g: Data, cat_id: int) -> Data:
    keep = g.y != cat_id
    if bool(keep.all()):
        return g
    out = Data(x=g.x, edge_index=g.edge_index[:, keep], edge_attr=g.edge_attr[keep], y=g.y[keep],
               num_nodes=g.num_nodes)
    for k in ("window_id", "task_id", "split", "window_start", "window_end"):
        out[k] = g[k]
    return out


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "loao")
    out.mkdir(parents=True, exist_ok=True)
    write_run_info(out / "run_info.json", cfg, {"models": args.models, "task_categories": data.task_categories,
                                                  "protocol": "joint training on all other tasks; "
                                                              "learner.learn() called once (no continual aspect)"})
    device = get_device(cfg["train"]["device"])
    node_in = data.graphs(0, "train")[0].x.shape[1]
    cats = cfg["categories"]
    rows = []
    for held_task, held_cat in enumerate(data.task_categories):
        cat_id = cats.index(held_cat)
        train = [drop_category_edges(g, cat_id)
                 for t in range(data.n_tasks) if t != held_task for g in data.graphs(t, "train")]
        test = data.graphs(held_task, "test")
        for model in args.models:
            set_seed(cfg["seed"])
            learner = make_learner(model, cfg, data.meta["n_features"], num_classes(cfg), device, node_in=node_in)
            stats = learner.learn(train, tag=f"loao_{held_cat}")
            pr = predict_graphs(learner, test, cfg["label_mode"])
            m = core_metrics(pr["y_true"], pr["y_pred"], cfg["label_mode"])
            mask = pr["y_cat"] == cat_id
            pred_attack = pr["y_pred"][mask] > 0
            rows.append({"held_out_category": held_cat, "model": model,
                         "n_heldout_flows": int(mask.sum()), "n_benign_flows": m["n_benign"],
                         "heldout_detection_rate": float(pred_attack.mean()) if mask.any() else np.nan,
                         "fpr": m["fpr"], "binary_f1": m["binary_f1"],
                         "mean_confidence_heldout": float(pr["conf"][mask].mean()) if mask.any() else np.nan,
                         "train_seconds": stats.seconds})
            log.info("held-out %s | %s | detection %.4f | fpr %.4f", held_cat, model,
                     rows[-1]["heldout_detection_rate"], m["fpr"])
            del learner
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            pd.DataFrame(rows).to_csv(out / "loao.csv", index=False)
    df = pd.DataFrame(rows)
    print(df.pivot_table(index="held_out_category", columns="model", values="heldout_detection_rate").to_string())


if __name__ == "__main__":
    main()
