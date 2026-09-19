"""Incident grouping + false-alarm budget (improvement 3) on the final models.

    python -m experiments.run_incidents --dataset cicids2017

For every test window, flows are classified by the model saved after the last
task; flagged flows are grouped into incidents (connected components per
predicted category). The alert threshold is calibrated on VALIDATION benign
flows for each false-alarm budget. Reported per budget: flow alerts vs
incidents, incident precision, and the share of real attack flows that end up
inside a true incident.
Outputs: results/<ds>/multiclass/incidents/{incidents.csv, examples.json, run_info.json}
"""
import json

import numpy as np
import pandas as pd

from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.product.incidents import build_incidents, calibrate_threshold, incident_metrics
from src.product.response import propose_action
from src.training.learners import load_learner_checkpoint, make_learner
from src.utils.config import class_names, num_classes, resolve_path
from src.utils.repro import get_device, set_seed, write_run_info


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=["gnn_ewc_replay", "ffnn_ewc_replay"])
    p.add_argument("--budgets", nargs="*", type=float, default=[0.0, 0.01, 0.001])
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    set_seed(cfg["seed"])
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "incidents")
    write_run_info(out / "run_info.json", cfg, {"models": args.models, "budgets": args.budgets})
    df = data.df
    ips = (df["src_ip"].astype(str).to_numpy(), df["dst_ip"].astype(str).to_numpy())
    device = get_device(cfg["train"]["device"])
    ckpt = resolve_path(cfg, "checkpoints") / cfg["dataset"] / cfg["label_mode"]
    names = class_names(cfg)
    rows, examples = [], {}
    for model in args.models:
        L = load_learner_checkpoint(make_learner(model, cfg, data.meta["n_features"], num_classes(cfg), device,
                                                 node_in=data.graphs(0, "train")[0].x.shape[1]),
                                    ckpt / f"{model}_after_task{data.n_tasks - 1}.pt")
        val = [g for t in range(data.n_tasks) for g in data.graphs(t, "val")]
        pv = np.concatenate([L.predict_proba(g) for g in val]); yv = np.concatenate([g.y.numpy() for g in val])
        test = [g for t in range(data.n_tasks) for g in data.graphs(t, "test")]
        preds = [(g, L.predict_proba(g)) for g in test]
        for b in args.budgets:
            thr = 0.0 if b == 0 else calibrate_threshold(pv, yv, b)
            agg = {"incidents": 0, "true_incidents": 0, "flagged_flows": 0, "attack_in": 0.0, "n_attack": 0}
            all_inc = []
            for g, pr in preds:
                fi = g.flow_idx.numpy()
                inc = build_incidents(ips[0][fi], ips[1][fi], pr, names, threshold=thr, y_cat=g.y.numpy())
                m = incident_metrics(inc, g.y.numpy())
                n_att = int((g.y.numpy() > 0).sum())
                agg["incidents"] += m["incidents"]; agg["true_incidents"] += m["true_incidents"]
                agg["flagged_flows"] += m["flagged_flows"]; agg["n_attack"] += n_att
                agg["attack_in"] += (m["attack_flows_in_true_incidents"] or 0) * n_att if n_att else 0
                for i in inc:
                    i["window_id"] = int(g.window_id)
                all_inc += inc
            rows.append({"model": model, "budget": b, "threshold": thr, "flow_alerts": agg["flagged_flows"],
                         "incidents": agg["incidents"], "true_incidents": agg["true_incidents"],
                         "incident_precision": agg["true_incidents"] / agg["incidents"] if agg["incidents"] else float("nan"),
                         "alerts_per_incident": agg["flagged_flows"] / agg["incidents"] if agg["incidents"] else float("nan"),
                         "attack_flows_in_true_incidents": agg["attack_in"] / agg["n_attack"] if agg["n_attack"] else float("nan")})
            top = sorted(all_inc, key=lambda d: -d["severity"])[:5]
            examples[f"{model}@{b}"] = [{k: v for k, v in i.items() if k != "flow_indices"} | {"proposed": propose_action(i)}
                                        for i in top]
            print(rows[-1])
        pd.DataFrame(rows).to_csv(out / "incidents.csv", index=False)
        (out / "examples.json").write_text(json.dumps(examples, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
