# Overnight test report (2026-10-09)

Ran every test on every feature, built the 10 CSVs and the VM report, fixed what broke. Summary below.

## 1. Automated tests — ALL PASS
| Suite | Result |
|---|---|
| **pytest** (unit + integration, every module) | **103 passed**, 0 failed |
| **UI smoke** (every tab × desktop/phone × light/dark) | **44/44 page loads, 0 problems** |
| **API feature sweep** (every endpoint behind every tab) | **all real checks pass** (30 checks; the 2 initial flags were a test artifact + a real gap, both resolved) |

## 2. Every tab / feature — verified working
- **Overview, Models, Adaptation & trust** — results endpoints load for both datasets.
- **Reproducibility** — tuning, λ-sweep, run metadata load. *Fixed:* on CSE-CIC-IDS2018 it now shows the
  reused CIC-IDS2017 selections instead of a 404 error.
- **Incident queue** — scan, per-window incidents, incident report, **CEF export** (SIEM) all return 200.
- **Graph explorer** — window catalogue, graph, model-error overlay, per-flow explain all work.
- **Classify** — window classify and CSV upload both work (see §3).
- **Stream replay** — metrics, drift status, stream windows load.
- **Live sites** — sites, model, windows, incidents, live graph, replay, label, adapt all work.
- **Cyber range (the VMs)** — ran end to end (see §4).

## 3. Ten uploadable CSVs — in `sample_flows/`
Each is a real held-out CIC-IDS2017 window (full feature set, raw units). **All 10 verified to classify
through the model** (none rejected):

| File | GNN flagged as attack |
|---|---|
| 01_benign_traffic.csv | 0 (correct) |
| 02_dos_attack.csv | 290 |
| 03_portscan_attack.csv | 741 |
| 04_ddos_attack.csv | 750 |
| 05_bruteforce_attack.csv | 750 |
| 06_infiltration_attack.csv | 750 |
| 07_botnet_attack.csv | 0 (small/hard class) |
| 08_webattack_attack.csv | 26 |
| 09_mixed_attacks.csv | 965 |
| 10_nmap_scan_live.csv | 0 (real live scan — the generalisation gap) |

Upload any of them on the **Classify** tab. Regenerate with `python scripts/make_sample_csvs.py`.

## 4. VM-scan report — new feature
The cyber range now writes a **self-contained HTML report** after every run (`reports/cyber_range_*.html`)
and opens it automatically. It summarises all four phases in plain language. A sample run tonight:
- Attack #1: **0 / 1194** flagged (scan unknown to the model)
- Taught it → old-attack F1 **0.975 → 0.975** (kept, no forgetting)
- Attack #2 (fresh scan): **1109 / 1169** flagged
- Recorded DoS/PortScan/DDoS: still **96–100%** detected

## 5. Bugs found and fixed tonight
1. **Reproducibility** errored on CSE-CIC-IDS2018 → now explains the reused 2017 selections.
2. **Graph explorer & Classify** showed 4 models (others show 3) → both respect the Compare toggle now.
3. **Classify** listed benign-only windows (all models said "benign", looked broken) → attack windows only.
4. **Graph explorer** drew the same graph for every model in Ground-truth mode → picking a model now
   switches to Model-errors so the choice always has an effect.
5. **Live sites** was a wall of empty panels → redesigned into a clear 1→2→3 flow, empty panels hidden.

Everything is committed and pushed. The console is cleaned and the stack is running on your GPU.
