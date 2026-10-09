# 50 % review preparation — working notes

Branch `review-50-fixes`. Notes from the night before the 50 % completion review: what was checked, what was
changed, and what is still open.

## Freeze

* The tag `review-50-before` already existed on GitHub and points to `dcdbe56`, four commits **ahead of**
  `main` (`aa81d1d`). Those four commits (context baselines, LwF / DER++, cross-dataset run, paired-t
  statistics) are on no remote branch. The tag was not moved; `review-50-fixes` was branched from it, so the
  frozen state is `dcdbe56`, not `main`.
* Machine used tonight: Windows 11, RTX 3050 Ti Laptop (4 GB), Python 3.12.14 venv. **This is not the demo
  laptop** (GTX 1650): the Desktop shortcuts, Docker cyber range and the laptop's `cache/checkpoints/` are not
  here. The CIC-IDS2017 zip was downloaded and demo checkpoints were trained into `cache/` only (see Smoke
  check).

## Smoke check

Environment: `.venv` with Python 3.12.14, `torch==2.14.0+cu126`, then `pip install -r requirements.txt`
(`pip check`: no broken requirements). CIC-IDS2017 zip downloaded from the README's source and prepared with
`python -m experiments.prepare_data --dataset cicids2017`: 2,099,974 flows, 423 windows, cache key
`058f69000380`, **identical to the data behind the committed results** (`continual/seed42/run_info.json`).

The served checkpoints (`cache/checkpoints/`) are not in git. To serve the console here they were trained with
`python -m experiments.run_continual --seeds 42 --models gnn_ewc_replay gnn_naive ffnn_ewc_replay xgboost_static
--out-name _demo_ckpt_scratch` (≈ 6 min on the RTX 3050 Ti). Its results folder was moved out of the repository;
no file under `results/` came from it. On this machine its seed-42 numbers differ slightly from the committed ones
(GNN + EWC + replay 0.960 here vs 0.975 committed for seed 42, `continual/seed42/summary.csv`), the known CUDA non-determinism; the demo laptop serves its own
checkpoints.

| Check | Before fixes | After fixes |
|---|---|---|
| `python -m pytest` | **127 passed** (frozen tag `dcdbe56`) | **130 passed** (127 + 3 new context-feature tests) |
| `scripts/run_stack.ps1` | ML (:8001) and API (:8000) up; **dashboard (:8080) never started** in a folder whose path has a space | all three layers up |
| `scripts/run_stack.ps1 -Stop` | left the ML server running (orphan child process holding :8001) | all layers stopped |
| `python scripts/ui_smoke.py` | could not run (no dashboard) | **77 / 77 page loads, 0 problems** (desktop + phone, dark + light, both datasets, compare on/off) |

Demo pages walked by hand (Playwright, 1440 × 900, Compare models on):

* **Overview** with Compare models on: loads, no "not run yet".
* **Live sites → Sandbox → ▶ Replay into the live view, DoS**: first replay ≈ 8 s (live engine warm-up), later
  ones ≈ 7–8 s. 5,000 flows, 4,832 flagged DoS, a red SANDBOX site, graph, one incident.
* **Incident queue**, Live source: 1 incident, *DoS from 172.16.0.1, critical*, explanation, evidence bars, network
  context, dry-run `iptables -I INPUT -s 172.16.0.1 -j DROP`. Recorded source, *Recent* scope: 16 incidents over 20
  windows (DEMO.md says 14: that count comes from the demo laptop's checkpoints, see "Still open").
* **Graph explorer**: window #147 (DoS) renders with attack hosts highlighted.
* **Reproducibility**: loads, no "not run yet".
* **Drift replay** (DEMO step 3): `POST /demo/start` warm-starts all four models from the checkpoints and retrains
  mid-stream (17 of 200 windows in 40 s, 3 GNN retrains).
* Console: two `Failed to create chart: can't acquire context` messages appeared when pages were switched faster
  than charts finished drawing (a few seconds per page). Not reproduced by the smoke test, which waits per page;
  nothing visible breaks.

Backup screenshots: `docs/screens/review_50/` (01 Overview with compare, 02 Sandbox DoS replay, 03 Incident queue
with the incident open, 04 Graph explorer, 05 Reproducibility).

## Fixes

* `scripts/run_stack.ps1` — quote the dashboard script path passed to `Start-Process`; an unquoted path with a
  space made the dashboard layer exit at once (`can't open file 'D:\Continous'`).
* `scripts/run_stack.ps1` — `-Stop` kills each layer's process tree (`taskkill /T /F`); a venv's `python.exe` is
  a launcher and the server ran on as its child.
* `DEMO.md`, `DEMO_FOR_GUIDE.md`, `docs/LIVE_DEMO.md`, `README.md` (page table) — page and button names now match
  the console: *Drift replay* (not "Live stream"), *▶ Replay into the live view* (not "Replay recorded attack"),
  Incident-queue *Source → Recorded* and the *One window* / *Recent* scopes; README lists Live sites and Drift replay.
* No model, training, graph, evaluation or preprocessing code was changed (the only new files there are
  `src/preprocessing/context_features.py`, used by nothing but Step 4).

## Numbers corrected in the docs

Every value was checked against the CSV named in the last column.

| Where | Old | New | Source |
|---|---|---|---|
| README, Known limitations, ADWIN bullet | 2018: "beat the schedule on both cost and quality (24 vs 48 retrains, 0.943 vs 0.825), in one run" | 3 seeds: 23 vs 48 retrains, 0.836 ± 0.117 vs 0.828 ± 0.010; won seed 42, tied 44, lost 43 | `results/csecicids2018/multiclass/drift_seeds/summary.csv`, `per_seed.csv` |
| DEMO.md step 3 | "On 2018 (one run) it wins clearly (24 vs 48 retrains)" | 3 seeds: 23 vs 48 retrains, quality tie (0.836 ± 0.117 vs 0.828 ± 0.010) | same |
| DEMO.md step 4 | "12 held-out runs (six attacks, two seeds) … over 80 % in 6"; "DoS 98.6 % both seeds; DDoS 99.4 %, 82.6 %" | 18 runs (three seeds), over 80 % in 8; DoS 98.6 % ×3; DDoS 99.4 / 82.6 / 67.5 %; BruteForce 99.7 / 0.07 / 100 %; Botnet 8.5 / 84.9 / 11.0 % | `results/csecicids2018/binary/loao_seeds/per_seed.csv` |
| DEMO.md questions table, "Does the graph really help?" | "over 80 % in 6 of 12 held-out runs" | "8 of 18 (2018, 3 seeds)"; DDoS declining | same |
| README §3 and DEMO questions table, "Why not just XGBoost?" | "detects only 1.3 % of attack flows from categories it never saw" | detects 0 % of DoS, WebAttack, Botnet, PortScan, DDoS and 0.13 % of Infiltration; the 1.3 % is `detection_rate_seen` over all attack flows, almost all of it the BruteForce it was trained on (1,280 of 102,853 test attack flows) | `results/cicids2017/binary/continual/recall_matrix_xgboost_static.csv`, `summary.csv`, `results/cicids2017/multiclass/split_report/split_report.csv` |
| README §3 | EWC-only binary "did **not** replicate on CSE-CIC-IDS2018" | the only 2018 binary run (one seed, withdrawn in §6) had EWC-only at 0.539, retention 0; stated as such | `results/csecicids2018/binary/continual/summary.csv` |
| `scripts/docgen/doc_body_b.py` (technical-doc source) | unseen-attack table with seeds 42/43 only; "6 of 12" | seed-44 column added; "8 of 18" | `binary/loao_seeds/per_seed.csv` |
| `docs/guide/part1.html`, `part3.html` (project-guide source) | "6 of 12 tests", "2 seeds", "6 of 12 vs 0 of 12" | "8 of 18", "3 seeds", "8 of 18 vs 0 of 18" | same |
| `docs/guide/part2.html` | ADWIN "beat a fixed schedule on 2018 (one run)"; EWC "failed on 2018" | 23 vs 48 retrains, quality tie; EWC failed in the one withdrawn 2018 binary run and in multiclass on both datasets | `drift_seeds/summary.csv`, `binary/continual/summary.csv` |
| `results/interpretation_2018.md` | stale single-seed interpretation (ADWIN win, 0.881 GNN mean, binary comparison) | marked **superseded** at the top, pointing to README §1/§6; text kept | — (not read by any code) |

The PDFs in `docs/` (`GNN-IDS_Project_Guide.pdf`, `GNN-IDS_Technical_Documentation.pdf`) were built from the
sources above and still show the old numbers until rebuilt.

Checked and already correct (no change): 0.964 ± 0.020 and FPR 0.066 % (interleaved, 3 seeds,
`cicids2017/multiclass/continual/summary.csv`, `summary_std.csv`); 0.915 ± 0.031 (temporal, 5 seeds,
`continual_temporal/`); 2018 0.911 ± 0.042 vs FFNN 0.836 ± 0.029 (`csecicids2018/multiclass/continual/`);
0.952 → 0.431 (2017) and 0.922 → 0.729 (2018) under randomised sources (`ip_remap_seeds/summary.csv`);
topology-augmented 0.914 (seed 42) and 0.906 / 0.938 (`ip_remap_seeds`, `continual`, `appendix_topo`);
2017 drift 0.960 / 0.980 / 0.968 / 0.926 / 0.230, retrains 16.7 / 8 / 15 (`drift_seeds`, `drift_mixed_seeds`);
2017 LOAO DoS 67.7 / 62.7 / 68.0 %, Infiltration 67.7 / 50.9 / 56.6 %, WebAttack 54.2 / 100 / 8.3 %
(`cicids2017/binary/loao_seeds/summary.csv`); binary 0.9993 / 0.9991 / 0.9945, naive retention 0.76 / 0.003
(`cicids2017/binary/continual/summary.csv`); `docs/model-card.md` and `FEATURE_INVENTORY.md` already carried
the three-seed numbers.

## Preliminary: host-context baseline

**Preliminary: joint training only for the in-distribution comparison, 3 seeds, XGBoost settings untuned
(`configs/default.yaml: xgboost`), CIC-IDS2017 only.** Not in the README headline.

What was run: `python -m experiments.run_context_baseline --dataset cicids2017 --seeds 42 43 44` and the same with
`--loao`. Host statistics per flow, inside its own 5,000-flow window, from endpoints and destination port only:
source out-degree, distinct destinations per source, distinct destination ports per source, destination
in-degree, distinct sources per destination, flows per (source, destination) pair, and each divided by the
window's flow count (`src/preprocessing/context_features.py`, checked on a hand-built 6-flow window in
`tests/test_context_features.py`). Results: `results/cicids2017/multiclass/context_baseline/`.

**Joint training, all tasks, interleaved test windows (the same 416,344 test flows as the headline table)**
(`joint_comparison.csv`)

| Model | Macro-F1 (3 seeds) | FPR | BruteForce | DoS | WebAttack | Infiltration | Botnet | PortScan | DDoS |
|---|---|---|---|---|---|---|---|---|---|
| XGBoost, flow features | 0.974 ± 0.000 | 0.010 % | 1.000 | 1.000 | 0.833 | 0.906 | 1.000 | 0.967 | 1.000 |
| XGBoost, flow + host statistics | **0.987 ± 0.000** | 0.054 % | 1.000 | 1.000 | 0.833 | 0.983 | 1.000 | 1.000 | 1.000 |
| GNN joint retrain (existing) | 0.951 ± 0.015 | 0.062 % | 1.000 | 1.000 | 1.000 | 0.959 | 0.904 | 1.000 | 1.000 |
| FFNN joint retrain (existing) | 0.955 ± 0.012 | 0.029 % | 1.000 | 0.999 | 0.917 | 0.910 | 1.000 | 0.960 | 1.000 |

**Leave-one-attack-out, binary** (`loao_binary_per_seed.csv`; GNN from `results/cicids2017/binary/loao_seeds/`),
held-out attack flows flagged, seeds 42 / 43 / 44

| Held out | XGBoost, flow | XGBoost, flow + host statistics | GNN (existing) |
|---|---|---|---|
| DoS | 0.7 / 2.6 / 0.4 % | **96.7 / 96.7 / 97.4 %** | 67.7 / 62.7 / 67.9 % |
| Infiltration | 26.9 / 40.3 / 39.7 % | **97.9 / 97.9 / 98.0 %** | 67.7 / 50.9 / 56.6 % |
| WebAttack (24 flows) | 0 / 0 / 0 % | **100 / 100 / 100 %** | 54.2 / 100 / 8.3 % |
| BruteForce | 0 / 0 / 0 % | 90.0 / 47.4 / 49.4 % | 0 / 0 / 0.8 % |
| Botnet | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % |
| PortScan | 98.8 / 98.7 / 99.0 % | 84.5 / 84.5 / 84.5 % | 100 / 100 / 100 % |
| DDoS | 99.2 / 99.7 / 99.8 % | 100 / 100 / 100 % | 100 / 100 / 100 % |

False-positive rate with host statistics: 0.00–0.28 % except held-out DoS (1.50 %); the GNN's is 0.00–0.20 %
except held-out DoS (0.21–1.96 %). The flow-only variant reproduces the existing `xgboost_static` LOAO rows
exactly, so the protocol is the same.

**Reading (plainly).** On CIC-IDS2017, *host statistics do as well as the graph or better*:

* In distribution, XGBoost on the flow's own features already beats both joint-retrained neural models (0.974 vs
  0.951 / 0.955), and adding host statistics raises it to 0.987. The GNN's +0.036 over the FFNN (§2) is real but
  is a gap between two neural models, not evidence that message passing beats a strong tabular model with the
  same window information.
* On unseen attacks, XGBoost with host statistics catches more of DoS, Infiltration and WebAttack than the GNN on
  every seed, and catches BruteForce (47–90 %), which the GNN misses. The GNN is ahead only on PortScan (100 % vs
  84.5 %). So the unseen-attack advantage of §1 is reproduced by window-level host counts without a graph network.
* Caveats: one dataset (2018 not run), joint training only (no continual comparison yet: the existing
  `xgboost_ctx_replay` / `ffnn_ctx_ewc_replay` models in `src/training/learners.py` are the way to run it), XGBoost
  not tuned, WebAttack has 24 test flows. The comparison is between models given the same windows; it does not say
  the GNN learns nothing, only that its measured advantages here are available to a much simpler model.

This answers RQ1 provisionally against the graph. It should be repeated on CSE-CIC-IDS2018 and in the continual
setting before any claim in the README changes.

## Still open

* **Not pushed.** Per the user's instruction nothing has been pushed to GitHub: the `review-50-fixes` branch, the
  local merge to `main` and the local `review-50` tag stay on this machine until the user says to push.
* **PDFs not rebuilt.** `docs/GNN-IDS_Project_Guide.pdf` and `docs/GNN-IDS_Technical_Documentation.pdf` still
  carry "6 of 12" and the 2018 one-run ADWIN claim; their sources are fixed. Do not show those two pages in the
  review, or rebuild them (`docs/guide/build_guide.py`, `scripts/docgen/make_doc.py`) on the laptop.
* **Incident counts in DEMO.md step 2** (4,986 flagged, 1 incident; 14 incidents over 20 windows) depend on the
  served checkpoints. They were not re-checked on the demo laptop; this machine's retrained checkpoints give 16.
  Read the number off the screen rather than quoting 14.
* **Cyber range and the Desktop shortcuts** (DEMO_FOR_GUIDE part 2) were not run: no Docker range here. Part 1
  (sandbox replay) is the fallback the guide already names.
* `results/RESULTS.md` still shows the 2018 drift and LOAO tables for seed 42 only; they are labelled "seed 42"
  and generated, so they were not hand-edited. Regenerating the report to include seed summaries is a code change
  to `experiments/make_report.py`, left for after the review.
