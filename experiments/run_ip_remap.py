"""Phase 8b: IP-leakage check (brief §7).

    python -m experiments.run_ip_remap --dataset cicids2017

Each model is trained ONCE through the task sequence and every evaluation is
scored under three test-time IP modes: none | permute | random_src
(see src/graph/ip_remap.py). Tabular models are included as a control: they
never see IPs, so their numbers must be identical across modes.
"""
from experiments.common import apply_selection, base_parser, config_from_args, results_dir
from src.evaluation.continual import run_task_sequence
from src.graph.ip_remap import make_transform
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.repro import set_seed, write_run_info

DEFAULT_MODELS = ["gnn_ewc_replay", "gnn_naive", "ffnn_ewc_replay"]
MODES = ["none", "permute", "random_src"]


def main():
    p = base_parser(__doc__)
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    args = p.parse_args()
    cfg = apply_selection(config_from_args(args), args)
    set_seed(cfg["seed"])
    prepare_dataset(cfg)
    data = load_processed(cfg)
    out = results_dir(cfg, args, "ip_remap")
    write_run_info(out / "run_info.json", cfg, {"models": args.models, "modes": MODES})
    transforms = {m: make_transform(m, cfg["seed"], cfg["ip_remap"]["pool_size"]) for m in MODES}
    summary = run_task_sequence(cfg, data, args.models, out, eval_transforms=transforms)
    last = summary[summary["after_task"] == summary["after_task"].max()]
    print(last.pivot_table(index="model", columns="ip_mode",
                           values=["accuracy_seen", "macro_f1_seen", "fpr_seen"]).to_string())


if __name__ == "__main__":
    main()
