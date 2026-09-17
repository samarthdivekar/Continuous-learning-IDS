"""One command that regenerates every reported number and figure from raw data.

    python -m experiments.reproduce_all --dataset cicids2017

Order (each step reads only files produced by earlier steps):
  1  prepare_data                        raw CSV -> processed table -> graph cache
  2  tune_val          (multiclass, val) epochs / replay-loss selection
  3  sweep_ewc_lambda  (multiclass, val) λ, γ selection  -> ewc_lambda_sweep/selected.json
  4  run_continual     (multiclass + binary, test, seeds)  core table
  5  run_drift_stream  (multiclass)       ADWIN vs periodic vs oracle vs never
  6  run_loao          (binary + multiclass)
  7  run_ip_remap      (multiclass)
  8  make_plots
  9  src.db.seed       load results into the database (for the API/dashboard)

Steps can be skipped with --skip (e.g. --skip tune sweep to reuse existing selections).

Exact commands used for the committed results:
  python -m experiments.reproduce_all --dataset cicids2017
  python -m experiments.reproduce_all --dataset csecicids2018 --seeds 42 --skip tune sweep seed --loao-modes binary
(2018 reuses the 2017 validation-selected hyper-parameters; see configs/csecicids2018.yaml.)
"""
import argparse
import subprocess
import sys
import time

STEPS = ["prepare", "tune", "sweep", "continual", "drift", "loao", "ipremap", "plots", "seed"]


def run(cmd: list[str]) -> None:
    print(f"\n=== {' '.join(cmd)}", flush=True)
    t0 = time.time()
    subprocess.run([sys.executable, "-m", *cmd], check=True)
    print(f"=== done in {time.time() - t0:.0f}s", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", default="cicids2017")
    p.add_argument("--seeds", nargs="*", default=["42", "43", "44"])
    p.add_argument("--skip", nargs="*", default=[], choices=STEPS)
    p.add_argument("--loao-modes", nargs="*", default=["binary", "multiclass"], choices=["binary", "multiclass"])
    p.add_argument("--dev", action="store_true")
    a = p.parse_args()
    d = ["--dataset", a.dataset] + (["--dev"] if a.dev else [])
    todo = [s for s in STEPS if s not in a.skip]

    if "prepare" in todo:
        run(["experiments.prepare_data", *d])
    if "tune" in todo:
        run(["experiments.tune_val", *d, "--label-mode", "multiclass"])
    if "sweep" in todo:
        run(["experiments.sweep_ewc_lambda", *d, "--label-mode", "multiclass"])
    if "continual" in todo:
        for mode in ("multiclass", "binary"):
            run(["experiments.run_continual", *d, "--label-mode", mode, "--seeds", *a.seeds])
    if "drift" in todo:
        run(["experiments.run_drift_stream", *d, "--label-mode", "multiclass"])
    if "loao" in todo:
        for mode in a.loao_modes:
            run(["experiments.run_loao", *d, "--label-mode", mode])
    if "ipremap" in todo:
        run(["experiments.run_ip_remap", *d, "--label-mode", "multiclass"])
    if "plots" in todo:
        for mode in ("multiclass", "binary"):
            run(["experiments.make_plots", *d, "--label-mode", mode])
    if "plots" in todo and not a.dev:
        run(["experiments.make_report"])
    if "seed" in todo and not a.dev:
        run(["src.db.seed", "--dataset", a.dataset, "--label-mode", "multiclass"])


if __name__ == "__main__":
    main()
