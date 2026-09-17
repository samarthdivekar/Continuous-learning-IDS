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
10. [Repository layout](#repository-layout)
11. [References](#references)

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

```bash
curl -L -o data/raw/CICIDS2017_improved.zip https://intrusion-detection.distrinet-research.be/CNS2022/Datasets/CICIDS2017_improved.zip
```

```bash
curl -L -o data/raw/CSECICIDS2018_improved.zip https://intrusion-detection.distrinet-research.be/CNS2022/Datasets/CSECICIDS2018_improved.zip
```

**Newer datasets (2024–2026).** We looked for newer enterprise-network flow datasets. The York University
BCCC releases (e.g. BCCC-CIC-IDS2017/2018, 2024) are re-extractions of the *same* 2017/2018 traffic with
a different feature extractor (NTLFlowLyzer), and are distributed only through a request form. Other
2024–2026 releases target IoT, QUIC, DNS or cloud-only DDoS, which are outside this project's LAN-gateway
scope. None were used. The loader is dataset-agnostic (`src/ingestion/`), so an additional CICFlowMeter-style
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

Add `--dataset csecicids2018` for the 2018 dataset, and `--dev` to any command for a fast 20 %-of-windows
development run (written to `results/dev/`, never reported).

Runtime on the reference machine for CIC-IDS2017: preparation ≈ 1 min; the full reproduction ≈ 3 h
(most of it in 3 seeds × 2 label modes × 9 models).

Every results directory contains `run_info.json`: seed, full resolved config, package versions, GPU,
the command line and the processed-data hash.

## Running the system

### Locally (SQLite, no Docker)

```bash
python -m src.db.seed --dataset cicids2017 --label-mode multiclass
```

```bash
python -m uvicorn src.api.app:app --port 8000
```

Open http://localhost:8000 for the dashboard. **Start live stream** replays the chronological stream
through four models at once (ours, GNN naive, FFNN + EWC + replay, static XGBoost): per-window
predictions, ADWIN drift flags, adaptations and periodic evaluation are written to the database, and the
charts update as it runs. **Retrain now** forces an adaptation cycle (logged as a `manual` drift event).
The "Task sequence" source shows the committed task-sequence results.

The API loads the checkpoints written by `run_continual` (first seed) from `cache/checkpoints/`.
Without them `/predict` reports the models as unavailable; the live demo still works because it trains
its own models from the cached graphs.

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

> ⚠️ **The Docker/PostgreSQL path has not been executed.** Docker was not available on the development
> machine. The compose file, Dockerfile, nginx config and the TimescaleDB hypertable setup in
> `src/db/session.py` were written against the documented APIs, but only the SQLite path is tested.
> Expect to fix small issues on first run.

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
One value per incoming window: the model's error rate on that window, assuming labels arrive with a delay
(e.g. analyst triage); a label-free confidence signal is available via `drift.signal: confidence`. Only
an *increase* flagged by ADWIN (δ = 0.002) triggers adaptation, with a 5-window refractory period.
Decreases are logged but trigger nothing. An adaptation cycle trains on the last 20 windows with the
model's own strategy (EWC + replay for ours), consolidates EWC, then resets ADWIN. No flag, no retraining.

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

RESULTS_PLACEHOLDER

## Known limitations and honest caveats

LIMITATIONS_PLACEHOLDER

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
dashboard/          Chart.js dashboard (served by FastAPI or nginx)
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
