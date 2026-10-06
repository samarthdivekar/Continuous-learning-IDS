"""What each split strategy leaves to test on, per task.

    python -m experiments.split_report --dataset cicids2017 --strategies interleaved temporal temporal_attack

For every strategy: windows per split and the number of test flows that carry the task's own attack. A
test block with no attack flows of its task cannot measure detection of that task at all, which is why
the plain `temporal` split is not used for the headline (see configs/default.yaml, split.strategy).
Prepares the data for a strategy if it is not cached yet.
Output: results/<ds>/<mode>/split_report/split_report.csv
"""
from __future__ import annotations

import pandas as pd

from experiments.common import base_parser, config_from_args, results_dir
from src.preprocessing.pipeline import load_processed, prepare_dataset
from src.utils.config import apply_overrides


def main():
    p = base_parser(__doc__)
    p.add_argument("--strategies", nargs="+", default=["interleaved", "temporal", "temporal_attack"])
    args = p.parse_args()
    base = config_from_args(args)
    cats = base["categories"]
    rows = []
    for strategy in args.strategies:
        cfg = apply_overrides(base, [f"split.strategy={strategy}"])
        prepare_dataset(cfg)
        data = load_processed(cfg)
        for t in range(data.n_tasks):
            task_cat = cats.index(data.task_categories[t])
            test = data.graphs(t, "test")
            rows.append({"strategy": strategy, "task": t, "category": data.task_categories[t],
                         "train_windows": len(data.graphs(t, "train")), "val_windows": len(data.graphs(t, "val")),
                         "test_windows": len(test),
                         "test_flows": int(sum(int(g.y.numel()) for g in test)),
                         "test_flows_of_task_attack": int(sum(int((g.y == task_cat).sum()) for g in test))})
    df = pd.DataFrame(rows)
    out = results_dir(base, args, "split_report")
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "split_report.csv", index=False)
    print(df.pivot(index=["task", "category"], columns="strategy", values="test_flows_of_task_attack").to_string())


if __name__ == "__main__":
    main()
