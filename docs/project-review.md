# Project review — senior engineering / product assessment

Reviewed against the repository as it stands, not against the README's description of itself. Every claim
below was checked in code or in `results/`.

**Overall: A- as a final-year engineering project. C+ as research. Not a product.**

The engineering is well above the standard for a final-year submission. The science has one methodological
flaw that a knowledgeable examiner will find in ten minutes, and most of the interesting conclusions rest on
one or three runs. The product framing is aspirational and should be dropped or narrowed.

---

## 1 · What is genuinely strong

* **Intellectual honesty.** Negative results are reported as prominently as positive ones: EWC alone fails,
  the label-free drift trigger fails, uncertainty-only labelling fails, topology augmentation is a trade-off,
  the 2018 GNN is unstable. Most student projects bury these. This is the single best quality of the work.
* **Reproducibility discipline.** Every number on screen comes from a file an experiment wrote; one command
  regenerates the lot; hyper-parameters were chosen on validation, not test.
* **Error-corrected datasets.** Using the Engelen/Liu corrected releases rather than the original CIC CSVs is
  a real contribution and a differentiator over most published work on this data.
* **Serving architecture.** Split model service, pooled connections, prediction caching, graceful degradation
  when the model service is down. This is proper systems work.
* **The product layer is conceptually right.** Alert → incident grouping, abstention, per-alert evidence and
  human-approved dry-run response are the right four ideas for making a detector usable.
* **74 tests across 12 modules** with synthetic fixtures, running in CI.

## 2 · The serious problems

### 2.1 The train/test split is optimistic, and the headline number inherits that

`src/graph/window_builder.py:77–85` assigns splits by **window position modulo 10** inside each task —
validation at position 5, test at positions 2 and 8. Test windows are therefore **interleaved with training
windows from the same attack session, minutes apart, with the same attacker hosts and the same campaign**.

This is the standard way NIDS results get inflated. Near-duplicate traffic sits on both sides of the split, and
a graph model keyed on host structure is exactly the kind of model that benefits. The config comment says the
interleave exists because "attacks are bursty", which is a real problem, but the cure is a temporal split with
a gap, not interleaving.

**Consequence:** 0.964 ± 0.020 is an upper bound under favourable conditions, not a deployment estimate. The
project never produces a temporal-split number, so the gap is unknown — and "unknown" is the worst answer to
give an examiner who asks.

### 2.2 No statistical inference anywhere

There is no significance test, no confidence interval, no bootstrap in `src/` or `experiments/` (checked).
Standard deviation over three seeds is reported, which is honest, but every comparative claim is then made by
eye:

* 2018: 0.881 ± 0.038 vs 0.836 ± 0.029. The README correctly says the mean gap is carried by one seed — but
  with n=3 and overlapping spreads, the honest statement is "no detectable difference", not "the GNN leads".
* 2017: 0.964 vs 0.928 for the FFNN ablation. Three seeds, no test. This is the ablation the whole "does the
  graph help?" question rests on.

### 2.3 Most of the interesting findings are n=1

| Finding | Seeds |
|---|---|
| Task sequence, 2017 multiclass and binary, 2018 multiclass | 3 |
| **2018 binary** | **1** |
| **Drift stream (ADWIN vs periodic vs oracle vs never)** | **1** |
| **Leave-one-attack-out, both datasets** | **1** |
| **IP-remap leakage test** | **1** |
| **Safety gate, label budgets, hybrid sampling, label-free trigger** | **1 each** |
| **Topology augmentation under randomised sources** | **1** |

The project already demonstrated that this model's 2018 score swings 0.855–0.925 across seeds. Single-run
results on the same model are therefore not evidence, they are anecdotes — including the ones the project is
most proud of (ADWIN efficiency on 2018, the 0.427 → 0.914 robustness recovery).

### 2.4 The in-distribution graph advantage is thin, and it is the headline

0.964 vs 0.928 over three seeds is a 0.036 gap with ±0.020 spread. The decisive result is elsewhere: **unseen
attacks, where the graph model gets 98.6–99.7 % and the per-flow model gets ~0 %**. The project leads with the
weaker number. That is a positioning mistake, not a science mistake, but it costs marks and credibility.

### 2.5 No performance envelope at all

No latency, no throughput, no memory profile anywhere in the codebase (checked). For an intrusion detection
system this is the first question any evaluator or buyer asks, and the README defers it to future work. "It
runs on a GTX 1650" is not an answer to "can it keep up with a 1 Gbps link?".

### 2.6 Hyper-parameter search is too thin to support the ablation claims

`results/cicids2017/multiclass/tuning/tuning.csv` sweeps **epochs × class-balanced loss — four configurations
per model**. λ and γ were swept for EWC. Nothing else: not window size (5,000 flows is asserted, never
justified), not hidden dimension, not learning rate, not replay budget, not neighbourhood sampling.

The claim "replay is what prevents forgetting, EWC does not" is therefore under-evidenced: EWC-only was given a
λ/γ grid, but replay-only was never given a budget sweep. A reviewer can reasonably ask whether EWC fails
because EWC fails, or because its grid was coarser than the attention replay received.

### 2.7 The task-incremental setup is an artefact of the benchmark

Real traffic does not arrive as clean blocks of one attack type at a time. The whole continual-learning
framing depends on this ordering, which comes from the dataset's capture schedule. The README mentions task
segmentation but never confronts the artificiality. A mixed/overlapping-attack stream would test whether the
method survives contact with reality.

### 2.8 A known broken behaviour ships in the product

`src/api/service.py`: `DemoRunner.ready` is set True on warm-start and reset only in the exception handler.
After any Live stream run, every prediction in the console is served by models trained on task 1 only, until
the service restarts. Measured: window 363 → 4,986 flagged → 0 after a run → 4,986 after restart. One line.

### 2.9 The console has no automated tests

~2,900 lines of hand-written JavaScript across 18 modules, verified only by me clicking through it. The Python
side has 74 tests; the UI has zero. For a system whose demo *is* the UI, that asymmetry is wrong.

### 2.10 "SOC-grade" is overstated

No authentication by default, no TLS, no rate limiting, no roles, SQLite, flow records stored in clear text,
`torch.load` of local artifacts. The README's security section is honest about this, which is good — but the
console's framing and the demo script lean on language ("security operations console") the deployment posture
does not earn.

## 3 · What is not useful and should go

| Item | Why | Action |
|---|---|---|
| **Classify → paste your own CSV** | With most features absent and imputed as 0, the verdict is meaningless. The new mapping preview makes the problem visible but does not make the output valid. | Require a full CICFlowMeter feature set, or delete the free-form paste and keep only file upload with validation. |
| **2018 binary results** | One seed, and the FFNN wins. It adds a weak claim nobody needs. | Run 3 seeds or delete the section. |
| **Topology-augmented model as a first-class model** | Loses on the main metric, kept only as a trade-off discussion. | Demote to an appendix experiment; remove from `MODELS` in the console entirely. |
| **Four separate label-budget runs in the UI** | Three of them are the same negative finding. | Keep the hybrid-vs-all-labels comparison; collapse the rest into one sentence. |
| **Dual deployment paths (Docker + `run_stack.ps1`)** | Two ways to run, one maintained. Docker was verified once and has not been exercised since. | Pick the script, mark Docker as unverified or delete it. |
| **`gnn_replay`, `ffnn_naive`, `gnn_ewc` in the default UI model list** | Ablations, not models a user chooses. | Already behind the compare toggle — keep them out of every default view and out of the Incident queue's detector dropdown. |
| **The five-step tour** | Demo sugar. Harmless, but it is the first thing to cut if the UI needs simplifying further. | Keep for now. |

## 4 · What should be implemented, in priority order

### P0 — credibility (do these before any examiner sees it)

1. **Temporal split.** Add `split.strategy: temporal` — first 70 % of each task's windows to train, next 10 % to
   validation, last 20 % to test, with a one-window gap. Re-run the 2017 headline on both splits and report
   both. If the number drops, say so; a defended 0.90 beats an undefended 0.964.
2. **Statistics.** Five seeds for the headline table; paired comparison across seeds (Wilcoxon signed-rank or a
   bootstrap CI of the difference) for the three claims that matter: ours vs FFNN, ours vs replay-only, 2018
   ours vs FFNN. State explicitly where no difference is detectable.
3. **Fix the demo `ready` bug.**
4. **Throughput and latency benchmark.** Flows/second and per-window p50/p95 on GPU and CPU, with the measuring
   script in `experiments/`. One table, one paragraph.

### P1 — depth

5. **Replay-budget sweep** (0, 1, 5, 10, 20 subgraphs per task) so the "replay, not EWC" claim is evidenced
   symmetrically with the λ grid.
6. **Window-size sensitivity** (1k / 5k / 20k flows). Cheap, and it justifies a design choice that is currently
   an assertion.
7. **Mixed-attack stream**: interleave two attack types in one period and re-run the drift experiment.
8. **Calibration**: reliability diagram and expected calibration error alongside the conformal results.
9. **Seeds for the single-run experiments** that you intend to keep claiming: drift, LOAO, IP-remap.

### P2 — product and polish

10. **Narrow the product claim to one wedge** and write a one-page positioning note: who the user is, what
    alert volume they have, what this replaces or augments. "A continual-learning triage layer on top of an
    existing IDS's alert stream" is defensible; "a SOC console" is not.
11. **One real integration**: receive alerts over syslog, or ingest Zeek/Suricata output, rather than CSV upload.
12. **Playwright smoke tests** for the console: every tab loads, no console errors, with the model service up
    and down.
13. **Model card** (one page): intended use, training data, metrics with their split, known failure modes,
    out-of-scope uses.

## 5 · Harsh conclusion

The project is **over-built and under-proven**. There are 47 API routes, 8 console tabs, 14 experiment scripts,
a conformal abstention layer, an open-set detector, an incident grouper, an explanation engine, a response
workflow, active learning, a safety gate and a topology-augmented variant — and the central scientific claim
rests on an interleaved split with three seeds and no significance test.

Breadth has been pursued at the expense of defensibility. The strongest result in the entire repository — a
graph model detecting 98.6–99.7 % of attacks it was never trained on, where the per-flow baseline detects
essentially none — is buried under a headline number that is both weaker and more fragile.

If an examiner asks one hard question, it will be: *"your test windows sit between your training windows from
the same attack session — what happens on a temporal split?"* Today there is no answer. That single experiment
matters more than every feature added in the last month.

Cut the sprawl. Prove the core. Lead with the unseen-attack result.
