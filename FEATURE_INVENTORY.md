# GNN-IDS — full feature inventory (for cross-check)

Everything in the project, grouped. Tick as you verify.

---

## 1. The ML core (the research)

**Main model**
- **E-GraphSAGE** edge classifier — every 5,000-flow window becomes a graph (hosts = nodes, flows = edges
  with 83 CICFlowMeter features); each flow is classified benign or one of the attack categories. 69,128 params.
- IP addresses define the graph only — never used as features.

**Continual learning (the contribution)**
- **EWC** (Elastic Weight Consolidation), λ = 10, γ = 0.9 (chosen on validation).
- **Subgraph replay** — up to 10 stored windows per attack category, 2 replayed per training step.
- Learns attack categories one at a time (7 tasks on 2017, 6 on 2018) without catastrophic forgetting.

**All 13 models/baselines implemented** (for the comparison):
`gnn_ewc_replay` (ours), `gnn_naive`, `gnn_ewc`, `gnn_replay`, `gnn_joint`, `gnn_ewc_replay_topo` (appendix),
`ffnn_ewc_replay`, `ffnn_ewc`, `ffnn_replay`, `ffnn_naive`, `ffnn_joint`, `xgboost_static`.

**Drift / streaming**
- **ADWIN** drift detector; policies compared: adwin / periodic / oracle / never.
- **Safe-adaptation gate** — a retrain is a candidate; rolled back if macro-F1 / FPR / retention worsens.
- Stream orders: clean blocks vs mixed pairs.

**Trust / robustness**
- **Open-set / novelty detection** — energy, MSP, prototype scores ("unfamiliar traffic").
- **Conformal abstention** — abstains when unsure.
- **Calibration** — ECE / MCE / Brier (are the probabilities honest?).
- **IP-leakage tests** — permute hosts (must not change) vs randomise sources (topology dependence).
- **Topology augmentation** (appendix) — trade topology robustness for accuracy.

**Evaluation protocol**
- Splits: interleaved, temporal, temporal-attack; leave-one-attack-out (unseen attacks).
- Stats: bootstrap confidence intervals, Wilcoxon tests, 3–5 seeds.

---

## 2. Datasets
- **CIC-IDS2017** (error-corrected, Engelen 2021) — 7 attack tasks, all flows.
- **CSE-CIC-IDS2018** (error-corrected, Liu 2022) — 6 attack tasks, 15% label-agnostic sample.
- 35 reviewed research papers in `research paper/` (git-ignored).

## 3. Key measured results (all reproducible, in README)
- Temporal macro-F1 **0.915 ± 0.031**; interleaved **0.964**; 2018 **0.911 ± 0.042**.
- Graph vs per-flow: **+0.044 temporal / +0.036 interleaved**.
- Retention of first attack: **0.998–1.000** (naive retraining: 0).
- Unseen DoS (leave-one-out): **98.6% × 3 seeds** on 2018 (per-flow FFNN ≤ 0.07%).
- Window-size, replay-budget, drift (3 seeds), IP-remap (3 seeds), calibration, serving speed (5.5 ms/window GPU).

---

## 4. The system (the product stack)
Five layers, one deployment path (`scripts/run_stack.ps1`):
- **Database** — SQLite (local) / PostgreSQL+TimescaleDB.
- **Ingestion** — data prep + DB seed.
- **ML service** (port 8001) — models, graphs, live demo.
- **Public API** (port 8000) — REST.
- **Dashboard** (port 8080) — the console.

## 5. API — 50+ endpoints, grouped
- **Results** (read-only): `/results/{index,continual,confusion,drift,loao,ip_remap,tuning,run_info,data_summary,adaptation,conformal,open_set}`
- **Predict / graph**: `/predict`, `/graph/{id}`, `/explain/{id}/{edge}`, `/windows`, `/windows/catalog`
- **Incidents**: `/incidents/scan`, `/incidents/{id}`, `/incidents/{id}/report`, `/incidents/{id}/cef`, `/actions`, `/actions/{id}/decision`
- **Stream demo**: `/metrics`, `/drift-status`, `/stream/windows`, `/demo/start|stop|status`, `/retrain`
- **Live traffic**: `/sensor/pcap`, `/sensor/flows`, `/sensor/replay_recorded`, `/live/{sites,windows,graph,site_graph,incidents,incidents/cef,actions,model,score,label,unlabel,adapt,reset,drift,purge,fpr_study,recorded_flows}`

---

## 6. The console — 9 tabs
**Operate**
1. **Overview** — headline results in one screen (macro-F1, retention, FPR, retrains).
2. **Incident queue** — thousands of flagged flows → a handful of incidents; why flagged, feature attribution,
   proposed dry-run rule, approve/reject, decision log, CSV + CEF (SIEM) export.
3. **Live sites** — real/cyber-range/sandbox traffic scored per site; graph; incidents; teach-and-adapt (1-2-3 flow).
4. **Stream replay (demo)** — replays the recorded dataset through the models; ADWIN drift, adaptation, speed control.

**Evaluate**
5. **Models** — accuracy, forgetting (BWT), unseen attacks, IP-leakage; per-seed tables.
6. **Adaptation & trust** — drift/retraining, novelty, conformal abstention, alert load.
7. **Reproducibility** — the reproduce command, λ sweep, tuning, run metadata, seeds.

**More**
8. **Graph explorer** — any window as an interactive force graph; ground-truth or model-error overlay.
9. **Classify** — score a held-out window or an uploaded CSV of flows; every model side by side vs ground truth.

Also: guided tour, help/glossary, presentation mode, light/dark, command palette, dataset/mode/compare switches, service-status pills.

---

## 7. Live-traffic / deployment layer
- **Sensor** (`sensor/agent.py`) — captures a machine's traffic (Wireshark/dumpcap) or replays a pcap, ships flows.
- **Pinned CICFlowMeter** (Docker, `sensor/cicflowmeter.Dockerfile`) — converts packets → the exact training features; rejects a capture whose columns don't match; non-IP records dropped.
- **Live model** — scores each chunk inside the site's last 2 min (≤ 5,000 flows, the training window size); conformal abstention (no alarm when unsure attack-vs-normal → *Unsure* list); unfamiliar-traffic flag; per-site incidents over the last 15 min with dry-run rules, approve/reject into the decision log, CEF export.
- **Teach-and-adapt on live traffic** — label flows (analyst + time recorded, undo, bulk "normal" skips suspicious flows) → the model adapts on a copy (scoring continues), trained on merged site windows; **rolled back** if old-attack macro-F1, any category's recall, recorded-benign FPR or the site's held-back normal FPR worsens. Accepted updates survive a restart. Live drift = disagreement with analyst labels. Retention purge (7 days). FPR measurement tool.
- **Two-site (LAN/MAN)** — `run_stack.ps1 -BindHost <LAN/Tailscale IP>` (requires an API key) → sensors on different networks → one console.

## 8. Cyber range (the VMs)
- Self-contained, isolated Docker range (no route out): 6 servers each capturing its own traffic, 6 workstations making normal web / shell / mail sessions, 1 attacker.
- **Streamed live** into the console (site CYBER-RANGE) every few seconds — no batch upload at the end.
- Attacker runs nmap **port scans** (recon only, no DoS): a SYN scan, then a *different* TCP connect scan.
- Measures, with exact ground truth: false alarms on normal traffic before/after teaching, detection of each scan, the gate's verdict, no forgetting of recorded attacks, and latency.
- **Writes an HTML report** after each run (`reports/`), opens it automatically.

## 9. Desktop app
- **Control center** (`desktop/control_center.py`, tkinter) — start/stop stack, status, open console, run sensor,
  sandbox replay, **Run cyber range**.
- Launchers + Desktop shortcuts: "GNN-IDS Control Center", "Run Cyber Range (demo)".

## 10. Deliverables & docs
- `README.md` (full results), `docs/model-card.md`, `docs/positioning.md`, `docs/project-review.md`.
- `docs/GNN-IDS_Project_Guide.pdf` (53 pp), `docs/GNN-IDS_Technical_Documentation.pdf`.
- `DEMO_FOR_GUIDE.md`, `docs/LIVE_DEMO.md`, `OVERNIGHT_TEST_REPORT.md`.
- **10 sample CSVs** (`sample_flows/`) for the Classify tab.

## 11. Testing & reproducibility
- **117 automated tests** (pytest); **UI smoke test** (88 page loads: every tab × desktop/phone × dark/light, plus CSE-CIC-IDS2018, binary and compare mode).
- `experiments/reproduce_all.py` — regenerates every number with one command.
- Every result folder has `run_info.json` (seed, config, versions, GPU, data hash, command).

---

### The honest limitations (also part of the project — examiners value these)
- Never blocks traffic — dry-run only.
- A real modern attack (e.g. live nmap) is **not** detected out of the box — lab-trained model, real-traffic gap.
- Graph advantage depends on attackers being few hosts (NAT/spoofing breaks it).
- Drift detection needs labels; unseen-attack detection is unreliable for some categories.
