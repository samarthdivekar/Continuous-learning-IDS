# Continual-Learning GNN Intrusion Detection

A network intrusion detection system (NIDS) that models traffic as graphs (hosts = nodes, flows = edges),
classifies flows with an edge-featured GraphSAGE network, **keeps learning new attack types without
forgetting old ones** (EWC + subgraph replay) and **only retrains when an ADWIN drift detector confirms
that behaviour changed**.

Final-year B.Tech project. Every number in this repository is produced by the scripts in
`experiments/` from the public datasets and is written to `results/`. Where the evidence does not
support the expected story, the README says so.

> **Headline results and all tables: [`results/RESULTS.md`](results/RESULTS.md)** (generated from CSVs,
> never edited by hand). A summary with interpretation is in [Results](#results) below.

---

## Contents
1. [What is compared](#what-is-compared)
2. [Datasets](#datasets)
3. [Setup](#setup)
4. [Reproducing results](#reproducing-results)
5. [Running the system (API + dashboard)](#running-the-system)
6. [Design](#design)
7. [Evaluation protocol](#evaluation-protocol)
8. [Results](#results)
9. [Known limitations and honest caveats](#known-limitations-and-honest-caveats)
10. [Future work](#future-work-scoped-out-deliberately)
11. [Repository layout](#repository-layout)
12. [References](#references)

---

## What is compared

| Model | Adapts to new attacks? | Remembers old attacks? | Role |
|---|---|---|---|
| XGBoost, trained once on task 1 | no | yes (but blind to new) | static baseline |
| E-GraphSAGE, naive fine-tuning | yes | no (expected: catastrophic forgetting) | control |
| **E-GraphSAGE + EWC + subgraph replay + ADWIN** | yes | yes | **ours** |
| FFNN + EWC + replay (same flows, no graph) | yes | yes | ablation: does the graph help? |

Also run as component ablations / references: `gnn_ewc`, `gnn_replay`, `ffnn_naive`, and joint retraining
on all data so far (`gnn_joint`, `ffnn_joint`; a non-continual upper bound).

## Datasets

We use the **error-corrected** releases, not the original CIC CSVs. The originals contain documented
labelling and flow-construction errors (Engelen et al. 2021; Liu et al. 2022): mislabeled attack flows,
flows that never carried an attack payload, and CICFlowMeter bugs. Using corrected data is a deliberate
contribution of this project.

| Dataset | File | Size | Source |
|---|---|---|---|
| CIC-IDS2017 (improved) | `CICIDS2017_improved.zip` | 328 MB (2.1 M flows) | https://intrusion-detection.distrinet-research.be/CNS2022/Datasets/ |
| CSE-CIC-IDS2018 (improved) | `CSECICIDS2018_improved.zip` | 9.9 GB zip, 36 GB CSV (63.2 M flows) | same page |

Place both zips in `data/raw/`. The 2017 archive is extracted automatically; the 2018 archive is read as a
stream directly from the zip (no 36 GB extraction).

**CSE-CIC-IDS2018 is subsampled label-agnostically.** Its 63.2 M flows do not fit 24 GB RAM with 83 float
features, so every flow is kept with probability 0.15 *regardless of its label* (seeded) — a 1-in-~7
sampled flow export (9.48 M flows, 1,898 windows). An earlier version kept all attacks and thinned only
benign flows; the integrity review showed that let ground-truth labels decide which edges the GNN saw
(including in test windows), so it was replaced and every 2018 result was regenerated.

```bash
curl -L -o data/raw/CICIDS2017_improved.zip https://intrusion-detection.distrinet-research.be/CNS2022/Datasets/CICIDS2017_improved.zip
```

```bash
curl -L -o data/raw/CSECICIDS2018_improved.zip https://intrusion-detection.distrinet-research.be/CNS2022/Datasets/CSECICIDS2018_improved.zip
```

**Newer datasets.** Post-2018 candidates were reviewed and none were used: the BCCC releases (2024–25)
re-extract the *same* 2017/2018 traffic and sit behind a request form; UWF-ZeekData22 (2022) is 99.97 %
reconnaissance (effectively one attack class); LUFlow (2020–21) is real traffic but labelled only
benign/malicious/outlier; the NetFlow-v3 datasets (2025) re-encode older captures; TII-SSRC-23 (2023) is
the closest fit (CICFlowMeter-style flows, several attack families) and is the natural next dataset.
Only 2017/2018 have published error-correction studies, which this project relies on. The loader is dataset-agnostic (`src/ingestion/`), so an additional CICFlowMeter-style
dataset needs only a config overlay in `configs/` and, if its labels differ, entries in
`src/ingestion/labels.py`.

### Label handling
* Categories: Benign, BruteForce, DoS, WebAttack, Infiltration, Botnet, PortScan, DDoS (`configs/default.yaml`).
* `"<attack> - Attempted"` flows (attack traffic without a malicious payload, as tagged by the corrected
  releases) are relabelled **Benign** by default (`preprocessing.attempted_policy`: `benign | drop | attack`).
* CIC-IDS2017 "Infiltration - Portscan" (a port scan run from the compromised victim) is kept as
  **Infiltration**, as labelled by the dataset. Behaviourally it is a port scan, which explains much of
  the PortScan↔Infiltration confusion reported below.
* CSE-CIC-IDS2018 has no stand-alone PortScan category (its NMAP scan is part of Infiltration) and its
  FTP brute force is entirely "Attempted", so BruteForce there is SSH only.

## Setup

Tested on Windows 11, Python 3.12.10, NVIDIA GTX 1650 (4 GB), 24 GB RAM.

```bash
python -m venv .venv
```

Activate it (`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` elsewhere), then install
PyTorch **first**, from the index that matches your hardware:

```bash
pip install torch==2.14.0 --index-url https://download.pytorch.org/whl/cu126
```

(CPU only: use `https://download.pytorch.org/whl/cpu`.) Then:

```bash
pip install -r requirements.txt
```

PyTorch Geometric 2.8 is used **without** its optional compiled extensions (`pyg-lib`, `torch-scatter`,
`torch-sparse`), whose Windows wheels lag behind PyTorch releases. Everything needed (message passing,
batching) is pure Python; neighbour sampling is implemented in `src/graph/sampling.py`.
`requirements.lock.txt` is the full `pip freeze` of the environment that produced the results.

Run the tests:

```bash
python -m pytest
```

## Reproducing results

One command regenerates every number and figure from the raw zips:

```bash
python -m experiments.reproduce_all --dataset cicids2017
```

It runs, in order: data preparation → validation tuning → EWC λ/γ sweep (validation split) →
task-sequence experiment (multiclass + binary, seeds 42/43/44) → drift stream → leave-one-attack-out →
IP-remap → plots → `results/RESULTS.md` → database seed. Individual steps:

| Step | Command | Output |
|---|---|---|
| prepare | `python -m experiments.prepare_data --dataset cicids2017` | `data/processed/…`, `cache/graphs/…` |
| tuning (val) | `python -m experiments.tune_val` | `results/<ds>/multiclass/tuning/` |
| λ/γ sweep (val) | `python -m experiments.sweep_ewc_lambda` | `results/<ds>/multiclass/ewc_lambda_sweep/` |
| core table | `python -m experiments.run_continual --label-mode multiclass --seeds 42 43 44` | `results/<ds>/<mode>/continual/` |
| drift | `python -m experiments.run_drift_stream` | `results/<ds>/multiclass/drift/` |
| LOAO | `python -m experiments.run_loao --label-mode binary` | `results/<ds>/<mode>/loao/` |
| IP remap | `python -m experiments.run_ip_remap` | `results/<ds>/multiclass/ip_remap/` |
| figures | `python -m experiments.make_plots --label-mode multiclass` | `*.png` next to the CSVs |
| report | `python -m experiments.make_report` | `results/RESULTS.md` |

Add `--dev` to any command for a fast 20 %-of-windows development run (written to `results/dev/`,
never reported).

**CSE-CIC-IDS2018** was run with one seed and without the two joint-retraining reference models (compute
budget), reusing the CIC-IDS2017 validation selections (`tuning_from` in `configs/csecicids2018.yaml`).
The exact commands:

```bash
python -m experiments.prepare_data --dataset csecicids2018
python -m experiments.run_continual --dataset csecicids2018 --label-mode multiclass --seeds 42 --models xgboost_static gnn_naive gnn_ewc_replay ffnn_ewc_replay ffnn_naive gnn_ewc gnn_replay
python -m experiments.run_drift_stream --dataset csecicids2018 --label-mode multiclass
python -m experiments.run_continual --dataset csecicids2018 --label-mode binary --seeds 42 --models xgboost_static gnn_naive gnn_ewc_replay ffnn_ewc_replay ffnn_naive gnn_ewc gnn_replay
python -m experiments.run_ip_remap --dataset csecicids2018 --label-mode multiclass
python -m experiments.run_loao --dataset csecicids2018 --label-mode binary
```

Runtime on the reference machine (GTX 1650): CIC-IDS2017 preparation ≈ 1 min and full reproduction
≈ 3 h; CSE-CIC-IDS2018 preparation ≈ 40 min and the runs above ≈ 8 h.

Every results directory contains `run_info.json`: seed, full resolved config, package versions, GPU,
the command line and the processed-data hash.

## Running the system

### Without Docker (recommended on a laptop)

`scripts/run_stack.ps1` runs the same five layers as local processes: SQLite for data, the ML service
(port 8001), the public API (port 8000, forwarding ML calls exactly like the compose deployment) and a
small static server with an `/api` proxy in place of nginx (port 8080):

```bash
powershell -ExecutionPolicy Bypass -File scripts/run_stack.ps1
```

Open **http://localhost:8080**; stop with `scripts/run_stack.ps1 -Stop`. First load the results into the
database once with `python -m src.db.seed --dataset cicids2017 --label-mode multiclass` (the stack script
does this unless `-SkipSeed`). A single-process variant is `python -m uvicorn src.api.app:app --port 8000`.

The console has ten tabs in two groups, *Operate* and *Evaluate*. Every panel is fed by result files or live API data, and a missing
experiment shows "not run yet", never a number. A **Help** drawer (key `?`) gives a plain-language tour and
glossary and opens automatically on the first visit. Keys `1`–`0` switch tabs.

| Tab | What it shows |
|---|---|
| Overview | headline KPIs, the "adapts / remembers" verdict table computed from results, attack timeline, architecture |
| Incident queue | a window's alerts grouped into incidents; per-incident explanation (feature attribution, network context, plain-English summary); proposed containment rule; analyst approve / reject with a decision log (dry run) |
| Live Stream | replays the stream through four models; ADWIN flags, adaptations, per-window counts, drift feed, speed control, forced retrain |
| Graph Explorer | any window graph as an interactive force layout (zoom, hover, category filters) with a per-flow **model-error overlay** |
| Model Comparison | any metric over tasks for all models with ±1 std bands, recall heatmaps, BWT, confusion matrix after any task |
| Drift Analysis | ADWIN vs periodic vs oracle vs never: retrain cost vs final quality, error timelines |
| Generalisation | leave-one-attack-out detection and the IP-remap leakage test |
| Classify | run every model on a held-out window or on pasted/uploaded flows |
| Trust & novelty | open-set detection of unseen attacks and proposed new-category clusters, conformal abstention, alert → incident compression, gated / label-budgeted adaptation |
| Reproducibility | λ sweep, tuning table, EWC stability ratios, run metadata |

The live stream warm-starts from the task-1 checkpoints written by `run_continual` (first seed) in
`cache/checkpoints/`; without them it trains task 1 itself first.

### Docker Compose (PostgreSQL + TimescaleDB)

```bash
cp .env.example .env
```

```bash
docker compose up --build
```

Dashboard: http://localhost:8080 · API: http://localhost:8000/docs. Five containers: `ingestion`
(one-shot: prepare data + seed DB), `db` (TimescaleDB), `ml` (models, drift monitor, live stream),
`api` (public REST, forwards ML calls to `ml`), `dashboard` (nginx). The data, cache and results folders
are bind-mounted, so run the experiments on the host (GPU) first, or use
`docker compose --profile reproduce run --rm experiments` (CPU, slow).

Verified on the development machine (Docker Desktop 29.8, Compose 5.5): all five containers start,
TimescaleDB creates the five hypertables, and every endpoint works through nginx; that run found and fixed
two bugs (prediction storage in the split deployment, demo start-up time). Docker needs WSL 2 and hardware
virtualisation; on a 24 GB laptop the Docker VM competes with training for RAM, which is why the
Docker-free stack above is the day-to-day option.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | DB status, loaded models, device |
| POST | `/ingest` | store flow records (raw CICFlowMeter features, original or canonical names) |
| POST | `/predict` | classify posted flows, stored `flow_ids`, or a cached `window_id`; label + confidence per model |
| GET | `/metrics?source=continual\|stream` | accuracy / macro-F1 / retention / FPR series per model |
| GET | `/drift-status` | recent drift events, drift/retrain counts, live-stream status |
| POST | `/retrain` | force an adaptation cycle in the running live stream |
| GET | `/graph/{window_id}` | node/edge summary of a window graph (node ids only, no IPs) |
| GET | `/stream/windows` | per-window counts (Benign / Known attack / Novel-drifted) |
| POST | `/demo/start`, `/demo/stop`; GET `/demo/status` | live stream control |
| GET | `/windows/catalog` | every window with task, split and attack composition |
| GET | `/graph/{window_id}?model=…` | adds per-edge misclassification counts for the chosen model |
| GET | `/results/{index,continual,confusion,drift,loao,ip_remap,tuning,run_info,data_summary}` | read-only access to `results/` (404 if an experiment has not run) |

All routes are also served under `/api/…`. Interactive docs: `/docs`.

---

## Design

### Graph construction (`src/graph/window_builder.py`)
* Flows are sorted by timestamp (never shuffled globally) and cut into **windows of 5,000 flows**
  (`window.mode: count | time`, configurable). Windows never cross a task boundary.
* Per window: unique IPs → nodes, each flow → a directed edge carrying its **83 scaled CICFlowMeter
  features**. IPs define topology only; they are never features. `Flow ID`, `Timestamp` and the ephemeral
  `Src Port` are dropped from the feature vector (`Dst Port` and `Protocol` are kept as L4 features).
* Node features carry no identity: `[1, log(1+out-degree), log(1+in-degree)]` (`graph.node_features:
  degree`; `constant` = the original E-GraphSAGE choice). Degree makes fan-out (scans) and fan-in (DDoS)
  visible to a mean aggregator.
* Graphs are cached per task/split under `cache/graphs/<dataset>_<hash>/`; the hash covers every config
  value that affects the data.

### Preprocessing (`src/preprocessing/`)
* ±inf/NaN → 0 (zero-duration flows; imputing keeps the edge instead of silently deleting it). Exact
  duplicate records removed.
* Scaling: `sign(x)·log1p(|x|)` → StandardScaler **fitted on task-1 training flows only** → clip to ±10.
  The log step matters: a scaler fitted on task 1 alone otherwise produces z-scores in the thousands for
  later volumetric attacks.
* **Task partition** (`tasks.py`): attack bursts of each category are found from timestamps, the timeline
  is cut at midpoints between consecutive bursts, and each segment becomes the task of its category.
  Benign flows belong to the segment they fall in. For CIC-IDS2017 this yields
  BruteForce → DoS → WebAttack → Infiltration → Botnet → PortScan → DDoS (Monday's benign traffic joins
  task 1).
* **Class imbalance:** class-weighted cross-entropy, `w_c = (N / (K·n_c))^0.5`, clipped to [0.05, 50],
  instead of undersampling. Undersampling benign flows would delete edges and distort the graphs. The
  square root tempers weights so ~100-flow classes do not blow up the false-positive rate.

### E-GraphSAGE (`src/models/egraphsage.py`)
Two layers, 64 hidden units, based on Lo et al. (2022) with two documented changes:
(1) messages combine the neighbour's embedding with the flow's features, `W[h_u ‖ e_uv]`, so information
travels beyond one hop (in the original, layer 2 re-aggregates raw edge features);
(2) incoming and outgoing flows are aggregated separately, since direction distinguishes a scanner from
a victim. Edge logits come from `MLP([h_src ‖ h_dst ‖ P·e_uv])`. The model is **inductive**: no per-node
parameters. Windows are trained full-batch; windows above 20,000 edges (time-mode) use GraphSAGE-style
edge neighbour sampling (fan-outs 25/10).

### EWC (`src/models/ewc.py`), with the three traps from the brief
1. **Penalty only from completed tasks:** `penalty()` is exactly 0 until `consolidate()` has run, and
   `consolidate()` is only called after a task or adaptation cycle finishes. Test: `test_no_penalty_before_first_consolidation`.
2. **Fisher from the raw task gradient:** `consolidate()` runs its own backward pass on plain task
   cross-entropy (no penalty, no replay term). Test: `test_fisher_ignores_penalty_gradient`.
3. **lr·λ·F kept small:** per-consolidation Fisher is max-normalised, online accumulation uses decay γ,
   gradients are clipped, `lr·λ·max(F)` is logged and warned on, and λ/γ are swept on validation data
   (λ ∈ {1…10⁴}, γ ∈ {0.9, 1.0}). Test: `test_stability_warning`.

### Subgraph replay (`src/models/replay_buffer.py`), v1: whole windows
One reservoir-sampled pool per attack category (10 windows each). A window joins the pool of every
category it contains, so the pool is an unbiased sample over all windows of that category ever seen.
**Fixed budget per training step:** exactly 2 replayed windows, category drawn uniformly first, so the
old:new ratio is constant however many categories accumulate, and big historical categories (DoS Hulk)
do not crowd out small ones. The FFNN uses the same design with individual flow rows (5,000 per
category, 512 rows per step). v2 (k-hop neighbourhoods) was not needed: 10 windows × 7 categories fits in
memory easily.

### ADWIN (`src/drift/adwin_monitor.py`, `src/evaluation/stream.py`)
The monitored signal is each flow's 0/1 misclassification, assuming labels arrive with a delay (e.g.
analyst triage); a label-free confidence signal is available via `drift.signal: confidence`. Every flow
of a window is fed to ADWIN (δ = 0.002), and before the stream starts ADWIN is calibrated on held-out
task-1 windows so it knows the normal error level. The direction of a change is read *at each detection*
(river 0.26.1 resets the detector completely on the update after a detection). Only an increase triggers
adaptation, with a 5-window refractory period; decreases are logged but trigger nothing. An adaptation
cycle trains on the last 20 windows with the model's own strategy (EWC + replay for ours) and
consolidates EWC. No flag, no retraining.

Two earlier designs failed and are documented in `tests/test_drift.py`: one mean value per window gave
ADWIN too few, too noisy samples to ever fire on the real stream; and deciding direction once per window
mislabelled an attack burst that started and ended inside a window as a decrease.

### IP-leakage mitigations (brief §7)
1. Inductive GraphSAGE, no node embeddings. 2. IPs never enter any feature tensor (unit-tested).
3. **IP-remap evaluation** (`src/graph/ip_remap.py`), applied to test graphs of an already trained model:
   * `permute`: random bijection of hosts. Tests identity leakage. With identity-free node features the
     model is invariant **by construction**; the experiment confirms it numerically.
   * `random_src`: every flow gets an independent random source host from a pool of 65,536. Destroys the
     "one attacker = one hub" structure, so it measures how much performance depends on host-level topology.

## Evaluation protocol

* **Splits:** within each task, windows are assigned by position (period 10: position 5 → validation,
  positions 2 and 8 → test, others → train). Whole windows stay intact, and test windows are spread over
  the whole attack period (attacks are bursty; a chronological tail split would miss whole attack types).
  Tabular models use exactly the same flows (they read `edge_attr` from the same cached graphs).
* **Tuning uses the validation split only.** Test windows are touched only by the final runs.
* **Metrics** (all reported together, `src/evaluation/metrics.py`):
  accuracy and macro-F1 over test flows of all tasks seen so far (accuracy over time); **retention** =
  recall of the first attack category on task 1's test windows after every later task (task-1 accuracy is
  also logged, but it is >99 % benign and would hide forgetting); **FPR** = benign flows flagged as any
  attack; BWT/forgetting from the per-category recall matrix; per-task confusion matrices.
* **Seeds:** 42, 43, 44 for the task-sequence table (mean ± std); the other experiments use seed 42.
  cuDNN is deterministic, but PyG scatter ops on CUDA are not bit-exact, so reruns can differ in the last
  digits.
* **Leave-one-attack-out:** joint training on all other tasks (stray flows of the held-out category removed),
  testing on the held-out task; detection = held-out attack flows predicted as *any* attack.

## Results

All numbers below are copied from [`results/RESULTS.md`](results/RESULTS.md), which is generated from
the result CSVs. CIC-IDS2017, test split, mean ± std over seeds 42/43/44, after the final task.

### 1. The core claim (multiclass, 7 attack categories learned in sequence)

| Model | Macro-F1 | Retention (task-1 recall) | FPR | BWT |
|---|---|---|---|---|
| XGBoost static (task 1 only) | 0.231 ± 0.000 | 1.000 | 0.00 % | 0.000 |
| GNN naive retrain | 0.289 ± 0.017 | **0.000** | 0.45 % | −0.830 |
| **GNN + EWC + replay (ours)** | **0.964 ± 0.020** | **1.000** | 0.07 % | −0.021 |
| FFNN + EWC + replay (ablation) | 0.928 ± 0.020 | 1.000 | 0.04 % | −0.029 |
| GNN + replay only | 0.948 ± 0.016 | 1.000 | 0.12 % | −0.040 |
| GNN + EWC only | 0.300 ± 0.001 | 0.000 | 0.37 % | −0.828 |
| GNN joint retrain (non-continual reference) | 0.951 ± 0.015 | 1.000 | 0.06 % | 0.031 |

* **The expected pattern holds.** The static model never learns new attacks; naive retraining forgets the
  first attack completely (retention 0 after the second task); our model learns every new category and
  keeps retention 1.0, matching a model retrained on all data.
* **Replay does the work, EWC does not.** Replay alone reaches 0.948; EWC alone is indistinguishable from
  naive retraining (BWT −0.828 vs −0.830) at *every* λ in a separately tuned sweep. This is the known
  weakness of EWC in class-incremental learning.
* **The graph helps, modestly.** 0.964 vs 0.928 for the FFNN ablation on the same flows and features, a
  gap of under two standard deviations. The FFNN has the lower false-positive rate (0.04 % vs 0.07 %).

### 2. Binary mode (attack vs benign)

Binary is domain-incremental (the "attack" class persists across tasks), and the picture changes:
ours 0.9993 macro-F1, FFNN + EWC + replay 0.9991, and **GNN + EWC only reaches 0.9945 with retention 1.0**
— on CIC-IDS2017, EWC alone works in the setting it was designed for (this did **not** replicate on
CSE-CIC-IDS2018, see §6). GNN naive keeps 0.76 retention; FFNN naive collapses
to 0.003. The static XGBoost detects only **1.3 %** of attack flows from categories it never saw.

### 3. Drift-triggered adaptation (stream of tasks 2–7, seed 42)

| Policy (our model) | Retrains | Final macro-F1 | Retention |
|---|---|---|---|
| ADWIN (drift-triggered) | 16 (46 flags) | 0.949 | 1.000 |
| Periodic, every 25 windows | 8 | 0.967 | 1.000 |
| Oracle (true task boundaries) | 6 | 0.952 | 1.000 |
| Never adapt | 0 | **0.232** | 1.000 |

Adapting is essential (0.95 vs 0.23), and ADWIN finds every task boundary without being told. But the
brief's efficiency goal is **not** met on this stream: ADWIN retrained 16 times where a fixed schedule
needed 8 and ended marginally lower. Attack bursts inside a task keep raising the error until the
model has adapted to them.

### 4. Unseen attacks (leave-one-attack-out, binary)

Each model is trained once on six categories and tested on the seventh:

| Held out | XGBoost | FFNN (per-flow) | GNN (graph) |
|---|---|---|---|
| DoS | 0.7 % | 3.0 % | **67.7 %** |
| WebAttack | 0.0 % | 0.0 % | **54.2 %** |
| Infiltration | 26.9 % | 49.3 % | **67.7 %** |
| PortScan / DDoS | ≥ 98.8 % | ≥ 98.8 % | 100 % |
| BruteForce / Botnet | 0 % | ≤ 0.8 % | 0 % |

This is the strongest evidence for the graph: host-level structure lets it flag attack types it has never
seen, where per-flow models see nothing. No model detects an unseen Botnet or BruteForce.

### 5. IP leakage (brief §7)

| Model | Normal | Hosts permuted | Sources randomised |
|---|---|---|---|
| GNN + EWC + replay | 0.950 | 0.950 | **0.427** |
| FFNN + EWC + replay | 0.947 | 0.947 | 0.947 |

Permuting host identities changes nothing (no IP memorisation). Randomising each flow's source, which
destroys the "attacker = one hub" structure, cuts the GNN's macro-F1 from 0.950 to 0.427 and raises its
FPR to 1.99 %. See the limitations.

### 6. CSE-CIC-IDS2018

CSE-CIC-IDS2018: 6 tasks (BruteForce → DoS → DDoS → WebAttack → Infiltration → Botnet), 15 % label-agnostic
flow sample, **one seed (42)**, hyper-parameters reused from CIC-IDS2017, no joint-retraining references.

**Multiclass task sequence**

| Model | Macro-F1 | Retention | FPR | BWT |
|---|---|---|---|---|
| XGBoost static | 0.282 | 1.000 | 0.00 % | 0.000 |
| GNN naive retrain | 0.280 | 0.000 | 0.50 % | -0.998 |
| **GNN + EWC + replay (ours)** | 0.855 | 1.000 | 0.51 % | -0.032 |
| FFNN + EWC + replay (ablation) | 0.850 | 1.000 | 0.07 % | -0.028 |
| GNN + replay only | 0.872 | 1.000 | 0.51 % | -0.041 |
| GNN + EWC only | 0.286 | 0.000 | 0.00 % | -0.831 |
| FFNN naive retrain | 0.282 | 0.000 | 0.00 % | -0.970 |

**Binary task sequence**

| Model | Macro-F1 | Retention | Detection | FPR |
|---|---|---|---|---|
| XGBoost static | 0.5136 | 1.000 | 2.8 % | 0.00 % |
| GNN naive retrain | 0.5297 | 0.000 | 4.5 % | 0.00 % |
| **GNN + EWC + replay (ours)** | 0.9765 | 1.000 | 100.0 % | 0.53 % |
| FFNN + EWC + replay (ablation) | 0.9954 | 1.000 | 99.9 % | 0.10 % |
| GNN + replay only | 0.9771 | 1.000 | 99.9 % | 0.51 % |
| GNN + EWC only | 0.5393 | 0.000 | 5.5 % | 0.00 % |
| FFNN naive retrain | 0.5263 | 0.000 | 4.1 % | 0.00 % |

**Drift-triggered adaptation** (stream of tasks 2–6)

| Model / policy | Drift flags | Retrains | Final macro-F1 | Retention |
|---|---|---|---|---|
| GNN + EWC + replay (ours) / adwin | 50 | 24 | 0.943 | 1.000 |
| GNN + EWC + replay (ours) / periodic | 0 | 48 | 0.825 | 1.000 |
| GNN + EWC + replay (ours) / oracle | 0 | 5 | 0.999 | 1.000 |
| GNN + EWC + replay (ours) / never | 0 | 0 | 0.155 | 1.000 |
| GNN naive retrain / adwin | 39 | 20 | 0.281 | 0.000 |
| FFNN + EWC + replay (ablation) / adwin | 63 | 33 | 0.801 | 1.000 |
| XGBoost static / never | 0 | 0 | 0.282 | 1.000 |

**Unseen attacks** (leave-one-attack-out, binary; share of held-out attack flows detected)

| Held out | XGBoost | FFNN (per-flow) | GNN (graph) |
|---|---|---|---|
| Botnet | 0.0 % | 0.0 % | 8.5 % |
| BruteForce | 0.0 % | 0.0 % | 99.7 % |
| DDoS | 0.0 % | 0.0 % | 99.4 % |
| DoS | 90.1 % | 0.1 % | 98.6 % |
| Infiltration | 0.0 % | 0.0 % | 0.0 % |
| WebAttack | 0.0 % | 0.0 % | 0.0 % |

**IP-remap** (macro-F1 of the same trained model)

| Model | Normal | Hosts permuted | Sources randomised |
|---|---|---|---|
| GNN + EWC + replay (ours) | 0.948 | 0.948 | 0.754 |
| GNN naive retrain | 0.281 | 0.281 | 0.277 |
| FFNN + EWC + replay (ablation) | 0.850 | 0.850 | 0.850 |

**What 2018 confirms, and what it does not.**

* **Forgetting prevention replicates.** Every replay-based model keeps retention 1.0; naive retraining,
  FFNN naive and EWC-only drop to 0 (BWT −0.83 to −1.00), exactly as on CIC-IDS2017.
* **EWC alone fails in both label modes here.** On 2017 binary, EWC-only reached 0.9945; on 2018 binary it
  scores 0.539 with retention 0. The 2017 binary result does not replicate, so replay, not EWC, is the
  component that reliably prevents forgetting.
* **ADWIN pays off on this stream.** 24 drift-triggered retrains beat a periodic schedule (48 retrains,
  0.825) on both cost and quality (0.943), and the model without adaptation collapses to 0.155. On
  CIC-IDS2017 the same detector over-triggered (16 vs 8 periodic). The efficiency claim therefore holds
  on one dataset and not the other.
* **GNN vs FFNN is inconclusive on 2018.** Single-seed results tie in multiclass (0.855 vs 0.850) and favour
  the FFNN in binary (0.995 vs 0.977) with a lower false-positive rate. That is on attacks the models
  were trained on.
* **On attacks never seen in training, the graph model wins clearly, more so than on 2017.** Holding one
  category out, the GNN flags 99.7 % of unseen BruteForce, 98.6 % of DoS and 99.4 % of DDoS flows. The
  per-flow FFNN flags ≤ 0.1 % of each, and XGBoost flags 90.1 % of DoS and 0 % of the others. None of
  the three detects unseen Infiltration (0 %). On Botnet the GNN manages only 8.5 %. WebAttack has
  just 7 held-out flows in the 15 % sample, too few to support any conclusion. These are the host
  fan-out/fan-in patterns a per-flow model cannot see. 2017 showed the same direction (DoS: GNN 67.7 % vs
  FFNN 3.0 %).
* **The GNN is unstable on Infiltration.** The IP-remap experiment re-trains the identical configuration
  (same seed, same data). Its "normal" column scores **0.948** where the task-sequence run scored **0.855**.
  The whole gap is one class: the task-sequence run flagged **9,196** benign flows as Infiltration
  (FPR 0.51 %), the IP-remap run **3** (FPR 0.0014 %), with the same ~97–99 % Infiltration recall. Nothing
  differs between the runs except CUDA's non-deterministic scatter operations, so the GNN's decision
  boundary between benign traffic and the NMAP-style Infiltration traffic is fragile. Single-seed 2018
  numbers for the GNN should be read as one draw from a wide distribution.
* **Topology dependence replicates, less severely.** Randomising source hosts drops the GNN from 0.948 to
  0.754 (2017: 0.950 → 0.427) while the FFNN is unaffected; host permutation changes nothing.

### 7. Product layer: novelty, abstention, incidents, explanations, safe adaptation

These features sit on top of the trained continual models. They are evaluated with the same per-task checkpoints and test splits as §1–6. They answer questions a security team asks before trusting a detector. Scripts: `experiments/run_open_set.py`, `run_conformal.py`, `run_incidents.py`, and `run_drift_stream.py --out-name ...`.

**Would it notice an attack it was never taught?** (open-set detection)
After each task, the next task's attack category is still unknown. The detector must score it as more novel than known traffic. The table gives AUROC averaged over the unseen categories; 0.5 is chance.

| Dataset | Model | Score | Mean AUROC | Range |
|---|---|---|---|---|
| CIC-IDS2017 | FFNN + EWC + replay | energy | 0.471 | 0.019–0.973 (n=6) |
| CIC-IDS2017 | FFNN + EWC + replay | msp | 0.689 | 0.409–0.970 (n=6) |
| CIC-IDS2017 | FFNN + EWC + replay | prototype | 0.643 | 0.141–0.987 (n=6) |
| CIC-IDS2017 | GNN + EWC + replay (ours) | energy | 0.875 | 0.644–0.998 (n=6) |
| CIC-IDS2017 | GNN + EWC + replay (ours) | msp | 0.766 | 0.423–0.999 (n=6) |
| CIC-IDS2017 | GNN + EWC + replay (ours) | prototype | 0.749 | 0.177–0.997 (n=6) |

Flows flagged as novel are clustered (k chosen by silhouette) to propose a new category. On CIC-IDS2017 the largest GNN cluster is the true new attack for DoS (87 % pure), Infiltration (97 % pure), DDoS (100 % pure). For WebAttack, Botnet, PortScan the largest cluster is benign traffic, so the novelty signal there was mostly false alarms.

**Does it know when not to decide?** (class-conditional conformal prediction)
The model abstains, handing the flow to an analyst, when its conformal prediction set is not a single class. Thresholds are calibrated per class on validation windows.

| Dataset | Model | α | False alarms: always decide → abstain when unsure | Flows handed to analyst | Accuracy on flows it decides |
|---|---|---|---|---|---|
| CIC-IDS2017 | GNN + EWC + replay (ours) | 0.01 | 184 → 0 | 10.1 % | 99.49 % |
| CIC-IDS2017 | GNN + EWC + replay (ours) | 0.05 | 184 → 0 | 9.8 % | 99.77 % |
| CIC-IDS2017 | GNN + EWC + replay (ours) | 0.1 | 184 → 107 | 9.3 % | 99.97 % |
| CIC-IDS2017 | FFNN + EWC + replay | 0.01 | 118 → 89 | 2.6 % | 99.70 % |
| CIC-IDS2017 | FFNN + EWC + replay | 0.05 | 118 → 83 | 4.9 % | 99.32 % |
| CIC-IDS2017 | FFNN + EWC + replay | 0.1 | 118 → 82 | 9.0 % | 99.20 % |
| CSE-CIC-IDS2018 | GNN + EWC + replay (ours) | 0.01 | 9,219 → 9,202 | 0.5 % | 99.51 % |
| CSE-CIC-IDS2018 | GNN + EWC + replay (ours) | 0.05 | 9,219 → 9,202 | 2.8 % | 99.50 % |
| CSE-CIC-IDS2018 | GNN + EWC + replay (ours) | 0.1 | 9,219 → 0 | 3.5 % | 100.00 % |
| CSE-CIC-IDS2018 | FFNN + EWC + replay | 0.01 | 1,240 → 332 | 0.9 % | 99.98 % |
| CSE-CIC-IDS2018 | FFNN + EWC + replay | 0.05 | 1,240 → 137 | 4.6 % | 99.99 % |
| CSE-CIC-IDS2018 | FFNN + EWC + replay | 0.1 | 1,240 → 124 | 9.5 % | 99.99 % |

Which α works depends on the dataset. On CIC-IDS2017 the stricter settings remove all 184 GNN false alarms (α = 0.01 and 0.05), and at α = 0.10 107 remain, as expected, because a smaller α gives larger sets. On CSE-CIC-IDS2018 the direction reverses. The 9,219 false alarms are benign flows called Infiltration with high but not extreme confidence. True Infiltration flows in validation are so confident that, at α = 0.10, the Infiltration threshold requires p ≥ 0.997, so the false alarms fall into an empty set and are handed to an analyst. At α ≤ 0.05 the threshold (p ≥ 0.48–0.07) admits them. There is no single safe α. It has to be chosen on validation data for each deployment. The FFNN's false alarms are spread thinly and shrink gradually.

**Will analysts drown in alerts?** (alert → incident grouping, CIC-IDS2017 test windows)
Flagged flows of the same predicted category are joined into connected attacker/victim components. The false-alarm budget raises the confidence threshold until the validation false-positive rate fits the budget.

| Model | Budget | Flow alerts | Incidents | Real incidents | Attack traffic inside real incidents |
|---|---|---|---|---|---|
| GNN + EWC + replay (ours) | 0 | 101,913 | 50 | 84 % | 98.9 % |
| GNN + EWC + replay (ours) | 0.001 | 101,913 | 50 | 84 % | 98.9 % |
| GNN + EWC + replay (ours) | 0.0001 | 101,913 | 50 | 84 % | 98.9 % |
| GNN + EWC + replay (ours) | 1e-05 | 101,913 | 50 | 84 % | 98.9 % |
| FFNN + EWC + replay | 0 | 102,893 | 106 | 54 % | 99.9 % |
| FFNN + EWC + replay | 0.001 | 102,893 | 106 | 54 % | 99.9 % |
| FFNN + EWC + replay | 0.0001 | 102,666 | 65 | 85 % | 99.8 % |
| FFNN + EWC + replay | 1e-05 | 100,515 | 51 | 98 % | 97.7 % |

On CIC-IDS2017, about 100,000 flow alerts reduce to 50 incidents for the GNN. The budget does not change the GNN's numbers: its false alarms are confident enough to survive every threshold, which is consistent with the conformal result above. For the FFNN the budget matters, taking it from 106 incidents at 54 % precision to 51 at 98 %.

**Can the GNN be made less dependent on host identity?** (topology augmentation, CIC-IDS2017, seed 42; 3-seed confirmation pending)
During training, with probability 0.5 per window, every flow's source is reassigned to a random host from a pool of 65,536. This is the same perturbation as the `random_src` test. Macro-F1 after the last task:

| Model | Normal | Hosts permuted | Sources randomised |
|---|---|---|---|
| GNN + EWC + replay (ours) | 0.950 | 0.950 | 0.427 |
| … + topology augmentation | 0.969 | 0.969 | 0.914 |
| FFNN + EWC + replay | 0.947 | 0.947 | 0.947 |

**Explanations and response.** For any flagged flow, `GET /explain/{window}/{edge}` returns a gradient × input attribution over the flow's own features and the share of evidence that came from neighbouring flows. It also reports structural facts (fan-out, fan-in, distinct target ports) and a one-paragraph summary generated by rules, with no language model. `GET /incidents/{window}` groups alerts and proposes a containment action (block source, rate-limit to victim, or isolate host) with the exact iptables / Windows Firewall rule. `POST /actions/{id}/decision` records an analyst's approve / reject. **Nothing is ever executed:** approval is stored as a dry run. The *Incident queue* tab of the console is built on these endpoints.

## Known limitations and honest caveats

* **The GNN leans heavily on host topology.** When source hosts are randomised it falls to 0.427
  macro-F1 while the per-flow FFNN is unaffected. On these lab datasets each attack comes from very few
  hosts; a real network with many or spoofed attackers could look much more like the randomised case.
  The graph's advantage (and its unseen-attack detection) should be read with this in mind.
* **The graph advantage is small in-distribution and does not replicate on 2018.** 0.964 vs 0.928
  macro-F1 on CIC-IDS2017 multiclass; a tie in 2017 binary; a tie (0.855 vs 0.850) in 2018 multiclass and
  the FFNN ahead in 2018 binary (0.995 vs 0.977). The FFNN has the lower false-positive rate throughout.
  The GNN's clearest advantage is detecting *unseen* attack types (§4).
* **The GNN is unstable on 2018 Infiltration.** Two runs of the identical configuration differ by 0.09
  macro-F1 because one flags 9,196 benign flows as Infiltration and the other 3 (§6). CUDA scatter
  non-determinism is enough to tip it; 2018 was run with one seed, so its GNN numbers carry that
  uncertainty. More seeds on 2018 are the first thing to add.
* **ADWIN's efficiency is dataset-dependent.** On CIC-IDS2017 it over-triggers (16 retrains vs 8 periodic,
  6 oracle, with slightly lower quality); on CSE-CIC-IDS2018 it beats the periodic schedule on both cost
  and quality (24 vs 48 retrains, 0.943 vs 0.825). The refractory period and adaptation window were fixed
  a priori, not tuned; tuning them without a separate validation stream would overfit the test stream.
* **EWC alone is not reliable.** It fails in class-incremental (multiclass) on both datasets; in
  domain-incremental (binary) it worked on CIC-IDS2017 but failed on CSE-CIC-IDS2018. Replay is the
  component that consistently prevents forgetting; EWC adds little on top of it.
* **Small test classes.** WebAttack has 24 test flows and Botnet 73 in CIC-IDS2017; per-category numbers
  for them are noisy (one flow = 1–4 %).
* **Validation selections are within noise.** The chosen λ = 10, γ = 0.9 beats neighbouring settings by
  < 0.001 validation macro-F1, driven by a handful of WebAttack/Botnet flows; GNN training is not bit-exact
  on CUDA (±0.01 between identical runs). Other λ in the flat region would give similar test results.
* **CSE-CIC-IDS2018 is a 15 % label-agnostic flow sample, one seed, no joint references**, with
  hyper-parameters reused from 2017 (compute budget).
* **Delayed-label assumption.** Drift detection uses the model's error, so it assumes ground truth arrives
  (e.g. from analysts) shortly after traffic; the label-free confidence signal is implemented but not evaluated.
* **Labels, not payloads.** Layer 3/4 flow features only; "Infiltration" in CIC-IDS2017 is mostly the
  victim's internal port scan, which explains most PortScan↔Infiltration confusion.
* **Integrity review.** An adversarial review before the final runs found and fixed: label-dependent
  benign thinning in 2018 (would have leaked labels into GNN test graphs), an ADWIN direction bug, duplicate
  replay entries in drift adaptation, the EWC-only ablation inheriting another model's λ, and several
  serving bugs. All affected experiments were re-run.


## Future work (scoped out deliberately)

These were considered and **not built**, to keep the system focused and every claim measured. None of them is
claimed anywhere in this README.

| Idea | Why it is not here yet | What it would take |
|---|---|---|
| Temporal graph model (e.g. TGN) instead of fixed windows | windowed E-GraphSAGE already captures the fan-out / fan-in structure the results depend on | event-level memory module, a new evaluation protocol for streaming edges |
| Federated / multi-site continual learning | needs several independent networks' traffic; both datasets are single-site | site-partitioned simulation, secure aggregation of EWC Fisher and replay prototypes |
| Self-supervised pre-training on unlabelled traffic | would change the continual protocol (task 0 would see future-task traffic) | masked-edge pre-training on a disjoint capture, then the same task sequence |
| Live attack emulation (trace replay into a test network) | needs an isolated lab network; the recorded datasets already replay through the stream API | tcpreplay + CICFlowMeter → `/ingest` pipeline in a sandbox |
| Throughput benchmark / hardware offload | measured on one laptop GPU (GTX 1650), which says little about production rates | load generator against `/ingest` + `/predict`, profiling on server hardware |
| SIEM export, authentication, role-based access | deployment concerns, not research claims; the API is meant to sit behind a gateway | syslog/CEF exporter, OAuth2 in front of FastAPI, analyst roles for approvals |
| LLM copilot for incident narratives | explanations are rule-generated today, which keeps them exactly faithful to the model | a local model (e.g. via Ollama) that rephrases, never invents, the `/explain` facts |

## Repository layout

```
configs/            default.yaml + per-dataset overlays
src/ingestion/      CSV/zip loader, column normalisation, label mapping
src/preprocessing/  cleaning, task partition, scaling, pipeline + loading
src/graph/          window builder, neighbour sampling, IP remap
src/models/         baseline_xgb, egraphsage, ffnn, ewc, replay_buffer
src/training/       continual learners (uniform interface over all models)
src/drift/          ADWIN monitor
src/evaluation/     metrics, task-sequence harness, streaming simulation
src/db/             SQLAlchemy schema, session (SQLite/Timescale), seeding
src/api/            FastAPI public app, ML service app, service layer + live demo
dashboard/          10-tab console (Chart.js + d3-force; served by FastAPI, nginx or scripts/dashboard_server.py)
scripts/            run_stack.ps1 (Docker-free five-layer stack), dashboard_server.py
experiments/        every script that produces a reported number
results/            committed CSV/JSON/PNG outputs + RESULTS.md
tests/              pytest suite (synthetic fixtures only)
docker/, Dockerfile, docker-compose.yml
```

## References

* G. Engelen, V. Rimmer, W. Joosen. *Troubleshooting an Intrusion Detection Dataset: the CICIDS2017 Case Study.* IEEE SPW (WTMC) 2021.
* L. Liu, G. Engelen, T. Lynar, D. Essam, W. Joosen. *Error Prevalence in NIDS datasets: A Case Study on CIC-IDS-2017 and CSE-CIC-IDS-2018.* IEEE CNS 2022.
* I. Sharafaldin, A. H. Lashkari, A. A. Ghorbani. *Toward Generating a New Intrusion Detection Dataset and Intrusion Traffic Characterization.* ICISSP 2018.
* W. W. Lo, S. Layeghy, M. Sarhan, M. Gallagher, M. Portmann. *E-GraphSAGE: A Graph Neural Network based Intrusion Detection System for IoT.* IEEE/IFIP NOMS 2022.
* W. Hamilton, R. Ying, J. Leskovec. *Inductive Representation Learning on Large Graphs.* NeurIPS 2017.
* J. Kirkpatrick et al. *Overcoming catastrophic forgetting in neural networks.* PNAS 2017.
* A. Chaudhry et al. *On Tiny Episodic Memories in Continual Learning.* 2019.
* A. Bifet, R. Gavaldà. *Learning from Time-Changing Data with Adaptive Windowing.* SIAM SDM 2007.
* D. Lopez-Paz, M. Ranzato. *Gradient Episodic Memory for Continual Learning.* NeurIPS 2017.
