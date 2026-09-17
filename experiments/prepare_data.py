"""Phase 1 + 4: raw CSVs -> cleaned, task-partitioned, scaled flow table -> cached window graphs.

    python -m experiments.prepare_data --dataset cicids2017
"""
from experiments.common import base_parser, config_from_args
from src.preprocessing.pipeline import prepare_dataset


def main():
    p = base_parser(__doc__)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    cfg = config_from_args(args)
    prepare_dataset(cfg, force=args.force)


if __name__ == "__main__":
    main()
