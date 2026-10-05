# Next-session prompt

Copy everything in the block below into a fresh session.

---

```
You are continuing my final-year project: a Continual-Learning GNN Intrusion Detection System
(repo: Continuous-learning-IDS, Windows, .venv, GPU GTX 1650).

START BY READING, in this order:
  docs/project-review.md    — the senior review; this is your brief
  README.md                 — current claims; every number in it must be defensible
  docs/ui-changelog.md      — what the console does today
  docs/GNN-IDS_Technical_Documentation.pdf — architecture, 47 routes, every UI control

GOAL
Make the project defensible rather than bigger. The engineering is already strong; the science is
not yet. Breadth has been bought at the cost of proof. Your job is to prove the core, cut the
sprawl, and make the README lead with the result that actually differentiates the work.

SETTLED DECISIONS — do not revisit
1. KEEP every baseline and ablation model (xgboost_static, gnn_naive, ffnn_ewc_replay,
   gnn_ewc, gnn_replay, the joint upper bounds). They are the evidence, not overhead. Measured:
   all four served models load in 0.29 s and hold 0.7 MB of GPU memory; startup is dominated by
   `import torch` (3.7 s) and torch_geometric (3.6 s). Cutting models saves nothing. Do not
   propose it again.
2. The console already defaults to one model with a "Compare models" toggle. Keep that.
3. Dry-run only: nothing in the UI or API may execute a firewall rule, ever.

HARD CONSTRAINTS — violating any of these fails the task
A. No number in README/results/docs may change unless the experiment that produces it was
   re-run in this session. Never hand-edit a metric. If a re-run contradicts a written claim,
   change the claim, not the number, and tell me explicitly.
B. All existing tests must pass at every commit (`python -m pytest`, currently 74). Do not
   delete or weaken tests; add tests for new behaviour.
C. Dashboard stays no-build: plain ES modules, Chart.js + d3-force from the already-allowed CDN,
   self-hosted fonts, no bundler, no framework. Any new dependency must be named in your summary
   and approved by me first.
D. Every value rendered into the DOM stays escaped; API key stays in a header, never a URL.
E. One commit per task. The message states what was measured or removed, not what was attempted.
F. Long runs go in a detached background process writing to logs/, so a closed session does not
   kill them. Report progress; never block waiting.

=== P0 — CREDIBILITY (nothing else matters until these are done) ===

P0.1 TEMPORAL SPLIT
  Add `split.strategy: interleaved|temporal` to configs (default stays `interleaved`, so existing
  results remain valid). Temporal = first 70% of each task's windows to train, next 10% to
  validation, last 20% to test, with a one-window gap between blocks. Cache key must include the
  strategy so graph caches never mix.
  Why: today test windows sit at positions 2 and 8 of every 10 inside the same attack session —
  minutes from training data, same attacker, same campaign. The headline 0.964 inherits that.

P0.2 RE-RUN THE HEADLINE ON BOTH SPLITS
  2017 multiclass, 5 seeds (42-46), both strategies. Write temporal results to
  results/cicids2017/multiclass/continual_temporal/. Add a README subsection comparing them
  honestly, including the drop. A defended 0.90 is worth more than an undefended 0.964.

P0.3 STATISTICS
  Add experiments/stats.py. For each comparison below compute per-seed paired differences, a
  Wilcoxon signed-rank p-value, and a bootstrap 95% CI of the mean difference:
    - ours vs ffnn_ewc_replay (2017, both splits)   — "does the graph help?"
    - ours vs gnn_replay (2017)                     — "does EWC add anything?"
    - ours vs ffnn_ewc_replay (2018)
  Put the table in the README. Where the CI crosses zero, write "no detectable difference" in
  plain words. Do not describe a difference as a win without the test supporting it.

P0.4 FIX THE DEMO BUG
  src/api/service.py: DemoRunner.ready is set True on warm-start and reset only in the exception
  handler, so after any Live stream run every prediction is served by task-1 models until the
  service restarts (measured: window 363 → 4,986 flagged → 0 → 4,986 after restart). Reset it on
  finish, stop and error. Add a regression test: start a demo, stop it, assert active_learners()
  returns the checkpoint-loaded models. Then remove the warning banner I added to the Live tab.

P0.5 PERFORMANCE ENVELOPE
  experiments/benchmark_serving.py: flows/second and per-window p50/p95 latency for /predict and
  /incidents, GPU and CPU, cold and warm cache, plus model parameter counts and memory. Write
  results/benchmarks/serving.csv and a README table. This is the first question any evaluator
  asks about an IDS and the project currently cannot answer it.

=== P1 — DEPTH ===

P1.1 REPLAY-BUDGET SWEEP (0, 1, 5, 10, 20 subgraphs per task; 3 seeds). The claim "replay is what
     prevents forgetting, EWC alone fails" is currently asymmetric: EWC got a λ/γ grid, replay
     never got a budget sweep. Update or retract the claim based on the result.
P1.2 WINDOW-SIZE SENSITIVITY (1k / 5k / 20k flows, 3 seeds). 5,000 is currently an assertion.
P1.3 MIXED-ATTACK STREAM: interleave two attack categories inside one period and re-run the drift
     experiment. Report whether ADWIN still beats a fixed schedule when attacks are not in clean
     blocks. This tests the artificiality of the task-incremental setup.
P1.4 CALIBRATION: reliability diagram + expected calibration error beside the conformal results.
P1.5 SEEDS for every single-run experiment you intend to keep claiming: drift stream,
     leave-one-attack-out, IP-remap. Anything left at one seed must be labelled "single run,
     indicative only" wherever it appears.

=== DELETIONS (do these; update README, dashboard and the docs PDF) ===

D.1 Classify tab: remove the free-form CSV paste box. Keep file upload, and reject a file that is
    missing required features instead of imputing zeros — an imputed verdict is meaningless and
    currently looks authoritative.
D.2 2018 binary: run 3 seeds or delete the section from README and dashboard. One seed where the
    ablation wins is a claim you cannot defend.
D.3 gnn_ewc_replay_topo: demote to an appendix experiment. Out of the dashboard MODELS map, out
    of the main results tables, one README paragraph stating the trade-off.
D.4 Label-budget variants in the UI: show only all-labels vs hybrid-100; collapse drift_al20 and
    drift_labelfree_al100 into one sentence of prose.
D.5 Pick ONE deployment path. If Docker stays, verify it end to end this session and record the
    date; otherwise delete docker/, Dockerfile and docker-compose.yml and say so in the README.

=== P2 — POLISH ===
P2.1 Playwright smoke test: every tab loads with the model service up and down, failing on any
     console error. ASK ME before installing Playwright.
P2.2 docs/model-card.md: intended use, training data, metrics with the split they came from,
     known failure modes, out-of-scope uses.
P2.3 Positioning note (half a page): who the user is, what alert volume they have, what this
     augments. "A continual-learning triage layer on an existing IDS's alert stream" is
     defensible; "a SOC platform" is not.

=== FINAL STEP ===
Rewrite the README Results section so it LEADS with the unseen-attack result — the graph model
detects 98.6–99.7% of attacks it was never trained on where the per-flow model detects ~0% — and
presents in-distribution macro-F1 second, with its confidence interval. That is the result that
differentiates this work; it is currently buried under a weaker, more fragile number.
Then regenerate docs/GNN-IDS_Technical_Documentation.pdf (scripts/docgen) and update
docs/ui-changelog.md.

WORKING STYLE
- Report after each phase with what the numbers actually said, including when they contradict the
  README or weaken a claim. I would rather hear "the temporal split cost us 0.06" than see it hidden.
- Queue long runs in the background and keep working; do not idle.
- If a requirement here conflicts with a hard constraint, the constraint wins — tell me.
```
