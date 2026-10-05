"""Paired comparisons across seeds for the claims the project makes.

    python -m experiments.stats

For each comparison, every seed trains both models on the same data and seed, so the differences
are paired. Reported per comparison:

  * the per-seed differences (ours minus the other model)
  * the mean difference
  * a Wilcoxon signed-rank p-value, two-sided and one-sided ("ours is better")
  * a bootstrap 95 % CI of the mean difference (percentile, 10,000 resamples of the seed differences)
  * a verdict in words: a difference is called a difference only when the CI excludes zero

Read the limits before the numbers. With n paired seeds the exact two-sided Wilcoxon test cannot go
below 2 / 2^n: 0.0625 for five seeds and 0.25 for three. On these designs the test can never reach
p < 0.05 two-sided, however consistent the differences are, so it is reported for completeness and the
verdict rests on the bootstrap interval — which, with so few seeds, is itself crude and tends to be too
narrow. Treat every verdict here as indicative, not confirmatory.

Output: results/stats/comparisons.csv and results/stats/comparisons.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from src.utils.config import REPO_ROOT

RESULTS = REPO_ROOT / "results"
OURS = "gnn_ewc_replay"

# (label, dataset, mode, results folder, other model, the question it answers)
COMPARISONS = [
    ("2017 · interleaved", "cicids2017", "multiclass", "continual", "ffnn_ewc_replay", "does the graph help?"),
    ("2017 · temporal", "cicids2017", "multiclass", "continual_temporal", "ffnn_ewc_replay", "does the graph help?"),
    ("2017 · interleaved", "cicids2017", "multiclass", "continual", "gnn_replay", "does EWC add anything to replay?"),
    ("2017 · temporal", "cicids2017", "multiclass", "continual_temporal", "gnn_replay", "does EWC add anything to replay?"),
    ("2018 · interleaved", "csecicids2018", "multiclass", "continual", "ffnn_ewc_replay", "does the graph help?"),
]
METRICS = [("macro_f1_seen", "macro-F1", 1), ("fpr_seen", "false-positive rate", -1)]   # sign: +1 higher is better


def final_per_seed(dataset: str, mode: str, folder: str) -> pd.DataFrame:
    """Last-task metrics per (model, seed), normal IP mode only."""
    path = RESULTS / dataset / mode / folder / "summary_all_seeds.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    if "ip_mode" in df:
        df = df[df["ip_mode"] == "none"]
    return df[df["after_task"] == df["after_task"].max()]


def bootstrap_ci(diffs: np.ndarray, n_boot: int = 10_000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(diffs, size=(n_boot, len(diffs)), replace=True).mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


def compare(per_seed: pd.DataFrame, other: str, metric: str, sign: int) -> dict:
    a = per_seed[per_seed["model"] == OURS].set_index("seed")[metric]
    b = per_seed[per_seed["model"] == other].set_index("seed")[metric]
    seeds = sorted(set(a.index) & set(b.index))
    if len(seeds) < 2:
        raise ValueError(f"need at least two paired seeds for {OURS} vs {other}, have {seeds}")
    diffs = np.array([a[s] - b[s] for s in seeds])
    nonzero = diffs[diffs != 0]
    two = wilcoxon(nonzero).pvalue if len(nonzero) else float("nan")
    better = "greater" if sign > 0 else "less"            # "ours is better" in the metric's own direction
    one = wilcoxon(nonzero, alternative=better).pvalue if len(nonzero) else float("nan")
    lo, hi = bootstrap_ci(diffs)
    excludes_zero = lo > 0 or hi < 0
    if not excludes_zero:
        verdict = "no detectable difference"
    else:
        ours_better = (lo > 0) if sign > 0 else (hi < 0)
        verdict = f"{'ours' if ours_better else other} better (indicative, n={len(seeds)})"
    return {"seeds": " ".join(map(str, seeds)), "n": len(seeds),
            "ours_mean": float(a[seeds].mean()), "other_mean": float(b[seeds].mean()),
            "mean_diff": float(diffs.mean()), "diffs": " ".join(f"{d:+.4f}" for d in diffs),
            "wilcoxon_p_two_sided": float(two), "wilcoxon_p_one_sided": float(one),
            "wilcoxon_floor_two_sided": 2.0 / 2 ** len(seeds),
            "ci_low": lo, "ci_high": hi, "verdict": verdict}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", default=str(RESULTS / "stats"))
    args = p.parse_args()
    rows, missing = [], []
    for label, ds, mode, folder, other, question in COMPARISONS:
        try:
            per_seed = final_per_seed(ds, mode, folder)
        except FileNotFoundError as exc:
            missing.append(f"{label} vs {other}: {exc}")
            continue
        for metric, name, sign in METRICS:
            try:
                r = compare(per_seed, other, metric, sign)
            except ValueError as exc:
                missing.append(f"{label} vs {other} ({name}): {exc}")
                continue
            rows.append({"comparison": label, "question": question, "other": other, "metric": name, **r})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "comparisons.csv", index=False)

    lines = ["| Comparison | Question | Metric | Seeds | Ours | Other | Mean diff | Bootstrap 95 % CI | Wilcoxon p (2-sided / 1-sided) | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        pct = r["metric"] == "false-positive rate"
        f = (lambda v: f"{v * 100:.3f} %") if pct else (lambda v: f"{v:.3f}")
        fd = (lambda v: f"{v * 100:+.3f} pp") if pct else (lambda v: f"{v:+.3f}")
        lines.append(f"| {r['comparison']} | {r['question']} | {r['metric']} | {r['n']} | {f(r['ours_mean'])} | "
                     f"{f(r['other_mean'])} ({r['other']}) | {fd(r['mean_diff'])} | [{fd(r['ci_low'])}, {fd(r['ci_high'])}] | "
                     f"{r['wilcoxon_p_two_sided']:.3f} / {r['wilcoxon_p_one_sided']:.3f} | {r['verdict']} |")
    (out / "comparisons.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if missing:
        print("\nnot computed (results not on disk yet):")
        for m in missing:
            print("  -", m)


if __name__ == "__main__":
    main()
