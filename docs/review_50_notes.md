# 50 % review — work log (night of 9–10 October 2026)

Branch `review-50-fixes`, frozen state tagged `review-50-before` (pushed). Rules followed: no change to model,
training, graph, evaluation or preprocessing code except new files; no headline experiment re-run; every number in
the docs checked against `results/`.

## Before the freeze

* **The review experiment chains were stopped** (user decision, 19:10). They were writing new model rows into the
  headline folder `results/cicids2017/multiclass/continual/`, and a queued step would have added seeds 45–46 and
  changed the rehearsed numbers. Their partial output (step 1 of 16, seed 42 complete) is kept in
  `cache/review_chain_partial_20261009/`; `results/` was restored to the committed state. Re-run
  `scripts/review_chain.ps1` after the review: it skips finished steps.
* **Commits made earlier the same day, before this plan arrived, are inside the frozen tag** (`7d372e9`..`dcdbe56`):
  additive review baselines (`ffnn_ctx_*`, `xgboost_replay/joint`, `gnn_lwf`, `gnn_derpp`, `features.drop`), the
  cross-dataset script and the stricter statistics rule. They touch `src/training`, `src/graph`, `src/models` and
  `src/preprocessing`, but every default code path is unchanged and the full test suite passes on them. Not pushed
  to `main` before tonight.

## Smoke check

| Check | Before | After |
|---|---|---|
| Environment vs `requirements.lock.txt` | 71/71 pins match, no reinstall needed | — |
| `python -m pytest` | 127 passed | see Final checks |
| `scripts/ui_smoke.py` (strict: any console error fails) | 77 page loads, 0 problems | see Final checks |
| Demo pages (Overview + Compare, Sandbox DoS replay, Incident queue, Graph explorer, Reproducibility) | all render; screenshots in `docs/screens/review_50/` | — |

**Found by measuring, not by the smoke test** (`scripts/ui_timing.py`, new): after Live sites had been opened once,
its 2-second poll kept running on every other tab and stacked overlapping ticks — about 3 API calls a second for
the rest of the session — and each `/live/drift` call scanned all 200k live flows (1.3 s). This was the "lag between
windows".

## Fixes (one line each)

1. `dashboard/js/views/sites.js`, `dashboard/js/views/live.js` — polls run only while their tab is on screen and never
   overlap; a refresh requested mid-poll runs right after instead of being dropped.
2. `src/db/models.py`, `src/db/session.py` — index on `live_flows.labelled_at`, created in place on existing
   databases: `/live/drift` 1.3 s → 7 ms.
3. `dashboard/js/views/sites.js` — Live sites opens on the most recently active site, not the first in the list (an
   idle cyber-range from hours earlier).
4. `results/stats/` regenerated with the already committed rule (a difference counts only if both the bootstrap and
   the paired-t 95 % CI exclude zero). Analysis of the frozen CSVs only; no experiment re-run.

Known, not changed: a sandbox replay takes about 10 s to score server-side (the button shows a spinner); the graph
switches to the sandbox when it finishes.

## Numbers corrected in the docs (old → new, source)

An audit compared every number in `README.md`, `DEMO.md`, `DEMO_FOR_GUIDE.md`, `FEATURE_INVENTORY.md` and `docs/*.md`
with `results/` (several hundred claims; each claimed mismatch was re-checked independently before it was changed).

| Where | Old | New | Source |
|---|---|---|---|
| README Known limitations, ADWIN | 2018 "beat the schedule on both cost and quality (24 vs 48, 0.943 vs 0.825), in one run" | 3 seeds: about half the retrains (23 vs 48), ties on quality (0.836 ± 0.117 vs 0.828 ± 0.010) | `results/csecicids2018/multiclass/drift_seeds/summary.csv`, `per_seed.csv` |
| DEMO.md step 3 | "On 2018 (one run) it wins clearly (24 vs 48 retrains)" | same three-seed reading | same |
| DEMO.md step 3 | mixed stream "ADWIN is better (0.968 vs 0.926)" | "averages higher, not a detectable difference" | `results/cicids2017/multiclass/drift_mixed_seeds/per_seed.csv` |
| DEMO.md step 4 + questions | "12 held-out runs (two seeds) … over 80 % in 6 of 12"; "DoS 98.6 % both seeds" | 18 runs (three seeds), 8 of 18; DoS 98.6 % on all three; DDoS 99.4 / 82.6 / 67.5 % | `results/csecicids2018/binary/loao_seeds/per_seed.csv` |
| README §2 paired-statistics table | bootstrap-only verdicts | table regenerated with the t-interval column | `results/stats/comparisons.md` |
| README §2, §6, limitations; DEMO questions; model card; inventory | "the graph helps on both splits" (+0.036 interleaved), "2018: GNN ahead" (+0.075), "EWC helped on the temporal split" (+0.067) | only the temporal +0.044 survives; the other three are **no detectable difference** (paired-t CIs [−0.039, +0.110], [−0.072, +0.222], [−0.046, +0.180]) | `results/stats/comparisons.csv` |
| README §2 | 2018 per-seed gaps +0.095, +0.008 | +0.094, +0.009 | `results/csecicids2018/multiclass/continual/summary_all_seeds.csv` |
| README §1 table | FFNN BruteForce "≤ 0.02 %" | 0.0 % | `results/csecicids2018/binary/loao_seeds/per_seed.csv` |
| README §1 2017 table | GNN DoS seed 44 68.0 % | 67.9 % | `results/cicids2017/binary/loao_seeds/per_seed.csv` |
| README §3 | XGBoost "1.3 % of attack flows from categories it never saw" | 1.3 % overall, ~0.02 % of unseen-category flows | `results/cicids2017/binary/continual/seed*/final_predictions_xgboost_static` |
| README §3 | EWC alone "did not replicate on 2018" | untested: the only 2018 binary run was one seed and is withdrawn | `results/csecicids2018/binary/continual/` |
| README §6 | BWT −0.83 to −1.00 | −0.83 to −0.97 | `results/csecicids2018/multiclass/continual/seed*/forgetting_*.json` |
| README §7 | 2018 abstention "removes them gradually" | reverse direction of 2017: 16 / 5 / 0 at α = 0.01 / 0.05 / 0.10 | `results/csecicids2018/multiclass/conformal/conformal.csv` |
| README §7 | GNN false alarms "survive every threshold" (calibration, incidents) | they survive every incident budget; conformal α ≤ 0.05 removes them | `results/cicids2017/multiclass/conformal/conformal.csv`, `incidents/incidents.csv` |
| README §7 | gate "final quality similar, costs little" | macro-F1 0.962 vs 0.949, but final FPR 0.086 % vs 0.026 % | `results/cicids2017/multiclass/drift_gate/summary.csv` |
| README §7 | uncertainty sampling "detection stays high" | macro-F1 0.438, detection 0.81 (0.999 with all labels) | `results/cicids2017/multiclass/drift_al100/summary.csv` |
| DEMO.md step 5 | "Nobody detects unseen Infiltration" | on 2018 ≤ 0.3 % on all seeds; on 2017 about half | `results/*/binary/loao_seeds/per_seed.csv` |
| DEMO.md step 5 | topology training "recovers 0.914" | 0.914 is one seed; in-distribution 0.938 ± 0.063 vs 0.964 | `results/cicids2017/multiclass/ip_remap/`, README appendix sources |
| DEMO_FOR_GUIDE.md, LIVE_DEMO.md, positioning.md | "4 phases"; "it cannot forget"; "nothing flagged" on normal traffic; range numbers presented as results | 7 steps; gated with the actual rollback limits; normal traffic may be flagged before teaching; range runs marked as not part of `results/` | demo script and cyber-range reports |
| FEATURE_INVENTORY.md | "All 13 models", stats "bootstrap, Wilcoxon" | models with results listed; both-CI rule | `results/` folders, `experiments/stats.py` |

Thirty claims could not be tied to a CSV (live-demo counts read off the screen, cyber-range reports, run times);
DEMO.md now says which numbers are read off the screen rather than from `results/`.

## Preliminary: host-context baseline

**Preliminary — joint training only (no continual learning), 3 seeds, one dataset.** `experiments/run_context_baseline.py`,
`src/preprocessing/context_features.py`, test `tests/test_context_features.py`.

XGBoost (default settings, class weights as for the other models) trained once on the training windows of all seven
CIC-IDS2017 tasks and scored on the test windows of all tasks — the same windows, splits and 416,344 test flows as
the headline interleaved table. "ctx" adds 12 per-window host-context columns computed from endpoints and ports only.

| Model (interleaved, seeds 42–44) | Macro-F1 | FPR | Source |
|---|---|---|---|
| XGBoost + host context, joint | **0.987 ± 0.000** | 0.054 % | `results/cicids2017/multiclass/context_baseline/` |
| XGBoost flow features, joint | 0.974 ± 0.000 | 0.010 % | same |
| GNN + EWC + replay (ours, continual) | 0.964 ± 0.020 | 0.066 % | `results/cicids2017/multiclass/continual/` |
| FFNN joint | 0.955 ± 0.012 | 0.029 % | same |
| GNN joint | 0.951 ± 0.015 | 0.062 % | same |

Per category, flow-only XGBoost misses part of Infiltration (90.6 %) and PortScan (96.7 %); host context lifts them to
98.3 % and 100 %. WebAttack is 83.3 % for both (24 test flows).

**Reading.** In distribution, a jointly trained XGBoost already beats the jointly trained GNN (0.974 vs 0.951), and
host-context columns add another +0.013. So on CIC-IDS2017 the graph network does **not** add in-distribution accuracy
that tabular host statistics cannot match. Joint training sees all attacks at once, so this says nothing about
continual learning (XGBoost cannot learn sequentially without refitting on stored data), and nothing yet about unseen
attacks, the graph's remaining claim — see the LOAO run below.

### Unseen attacks (binary leave-one-attack-out, CIC-IDS2017, seeds 42–44)

Protocol of `experiments/run_loao.py` (train on every other task, stray held-out flows removed, test on the held-out
task's test windows). Check: the flow-only XGBoost reproduces the existing `xgboost_static` LOAO numbers exactly on
every seed, so the pipeline matches the original protocol. Share of held-out attack flows flagged, per seed
(`results/cicids2017/binary/context_baseline_loao/per_seed.csv`; GNN from `results/cicids2017/binary/loao_seeds/per_seed.csv`):

| Held out | XGBoost + host context | XGBoost flow only | GNN (graph) |
|---|---|---|---|
| DoS | **96.7 / 96.7 / 97.4 %** | 0.7 / 2.6 / 0.4 % | 67.7 / 62.7 / 67.9 % |
| Infiltration | **97.9 / 97.9 / 98.0 %** | 26.9 / 40.3 / 39.7 % | 67.7 / 50.9 / 56.6 % |
| WebAttack (24 flows) | **100 / 100 / 100 %** | 0 / 0 / 0 % | 54.2 / 100 / 8.3 % |
| BruteForce | **90.0 / 47.4 / 49.4 %** | 0 / 0 / 0 % | 0 / 0 / 0.8 % |
| PortScan | 84.5 / 84.5 / 84.5 % | 98.8 / 98.7 / 99.0 % | **100 / 100 / 100 %** |
| DDoS | 100 / 100 / 100 % | 99.2 / 99.7 / 99.8 % | 100 / 100 / 100 % |
| Botnet | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % |

Worst false-positive rate on the held-out task's benign flows: host-context XGBoost 1.50 % (held-out DoS), GNN 1.96 %
(held-out DoS); elsewhere both ≤ 0.3 %.

**Reading.** On CIC-IDS2017, per-window host statistics given to a tree model explain — and exceed — the graph
model's unseen-attack advantage: better on DoS, Infiltration, WebAttack and BruteForce, worse only on PortScan, with
similar false alarms. The README's claim that "host-level structure lets the graph model flag attack types a per-flow
model cannot see" holds for *host structure*, but this run says the **graph network is not needed to use it**. Not yet
checked: CSE-CIC-IDS2018 (where the graph's unseen-attack results are strongest), the continual setting, and more
seeds. Until then this is preliminary and is not in the README headline, as the plan requires.

### Unseen attacks on CSE-CIC-IDS2018 (same protocol, seeds 42–44)

Check: flow-only XGBoost again reproduces the existing `xgboost_static` LOAO numbers exactly (DoS 90.1 / 84.8 / 86.8 %).
(`results/csecicids2018/binary/context_baseline_loao/per_seed.csv`; GNN from `results/csecicids2018/binary/loao_seeds/per_seed.csv`)

| Held out | XGBoost + host context | XGBoost flow only | GNN (graph) |
|---|---|---|---|
| DoS | **100 / 100 / 100 %** | 90.1 / 84.8 / 86.8 % | 98.6 / 98.6 / 98.6 % |
| DDoS | 75.7 / 76.4 / 75.7 % | 0 / 0 / 0 % | 99.4 / 82.6 / 67.5 % |
| BruteForce | 0 / 0 / 0 % | 0 / 0 / 0 % | **99.7 / 0.07 / 100 %** |
| Botnet | 0 / 0 / 0 % | 0 / 0 / 0 % | **8.5 / 84.9 / 11.0 %** |
| Infiltration | 1.0 / 1.0 / 1.0 % | 0 / 0 / 0 % | 0 / 0 / 0.3 % |
| WebAttack | 0 / 0 / 0 % | 0 / 0 / 0 % | 0 / 0 / 0 % |

False-positive rate ≤ 0.04 % for the host-context model, ≤ 0.14 % for the GNN.

**Reading across both datasets.** Host statistics in a tree model reproduce most of the graph's unseen-attack
detection (DoS, DDoS, and on 2017 Infiltration, WebAttack and BruteForce, where they beat it). The graph network's own
remaining edge is on 2018 BruteForce (two of three seeds) and Botnet (one of three seeds) — real, but seed-unstable.
The honest claim is narrower than the README's: **most of the unseen-attack advantage comes from host-level
structure, which simple per-window statistics capture; the message-passing network adds detection on some 2018
attacks, unreliably.** Preliminary (joint training, 3 seeds); not in the README headline.

## Still broken or open, and how the demo avoids it

* The external-review experiment chains are paused (see top); the README still makes no claim from them.
* Cyber range not re-run tonight (optional step). The demo uses the sandbox replay, which always works.
