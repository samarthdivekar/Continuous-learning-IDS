# Continual-learning GNN intrusion detection — 50 % review summary

## Problem
Intrusion detectors trained once go stale as new attacks appear, and retraining them naively makes them forget the
attacks they already knew. This project asks whether a graph model of network traffic can keep learning new attack
types without forgetting, and retrain only when the traffic has actually changed. It is evaluated on the
error-corrected CIC-IDS2017 and CSE-CIC-IDS2018 datasets, with an analyst console that never blocks traffic.

## Architecture
1. **Flows** — CICFlowMeter records, 83 scaled features per flow.
2. **Window graph** — every 5,000 flows become one graph: hosts are nodes, flows are edges.
3. **E-GraphSAGE** — an edge-featured graph network classifies every flow into Benign or one of 7 attack categories.
4. **Replay + EWC** — stored windows of earlier attacks are replayed while learning a new one; EWC penalises changes to
   weights that mattered for old tasks.
5. **ADWIN** — a drift detector on the labelled error decides when to retrain.

## Results so far (README section, seeds)
| Result | Value | Seeds | README |
|---|---|---|---|
| Macro-F1 after 7 attacks, interleaved split | 0.964 ± 0.020 | 3 | §2 |
| Macro-F1 after 7 attacks, temporal split | 0.915 ± 0.031 | 5 | §2 |
| Retention of the first attack (naive retraining: 0) | 0.998–1.000 | 3 / 5 | §2 |
| False-positive rate, interleaved | 0.07 % | 3 | §2 |
| CSE-CIC-IDS2018 macro-F1 | 0.911 ± 0.042 | 3 | §6 |
| Graph vs per-flow FFNN, temporal (the only detectable gap) | +0.044 | 5 | §2 |
| Unseen attack caught > 80 % (2018, graph vs per-flow ≤ 0.07 %) | 8 of 18 runs | 3 | §1 |
| Unseen DoS (2018) | 98.6 % on every seed | 3 | §1 |
| Randomised source hosts (2017 / 2018) | 0.952 → 0.431 / 0.922 → 0.729 | 3 | §5, §6 |
| ADWIN vs fixed schedule (2018) | 23 vs 48 retrains, quality tied (0.836 vs 0.828) | 3 | §6 |

## Findings, including negative ones
* **Replay does the work; EWC adds little.** EWC alone fails (0.300); EWC on top of replay is not a detectable
  improvement on either split under the stricter paired test.
* **The graph's in-distribution advantage is small.** Only the temporal-split +0.044 survives a paired test needing
  both a bootstrap and a t interval to exclude zero; +0.036 (2017 interleaved) and +0.075 (2018) do not.
* **Topology dependence.** Randomising source hosts drops the GNN from 0.952 to 0.431 (2017); the per-flow model is
  unaffected. The graph's strength rests on attackers being few hosts.
* **Unseen attacks:** DoS and DDoS are caught across seeds; BruteForce and Botnet swap between seeds; Infiltration and
  WebAttack are missed on 2018.
* **ADWIN is not cheaper on 2017** (about twice the retrains of a fixed schedule); on 2018 it halves retrains but only
  ties on quality.

## Preliminary result (tonight; joint training only, 3 seeds, CIC-IDS2017)
A jointly trained XGBoost on flow features reaches **0.974** macro-F1 on the same test flows, above the jointly trained
GNN (0.951); adding 12 per-window host-statistics columns lifts it to **0.987**. In distribution, host statistics match
the graph. Whether they also match it on **unseen** attacks is below.

On **unseen** attacks (CIC-IDS2017, leave-one-attack-out, 3 seeds) the host-context XGBoost catches DoS 97 %,
Infiltration 98 %, WebAttack 100 % and BruteForce 47–90 %, against 63–68 %, 51–68 %, 8–100 % and ≈ 0 % for the GNN;
it is worse only on PortScan (84.5 % vs 100 %), with similar false alarms (worst 1.50 % vs 1.96 %). **Honest
reading: host statistics, not the graph network, carry the advantage on 2017.** RQ1 (below) must now test 2018 and the
continual setting before any graph claim is made.

## Completed vs remaining
| Completed | Remaining (as research questions) |
|---|---|
| Continual task sequence, 2 datasets, 3–5 seeds | **RQ1** graph vs host-statistics baseline, continually and on both datasets (preliminary joint result above) |
| Interleaved and temporal splits, paired statistics | **RQ2** shortcut-feature ablation (dst_port, protocol, init-window) and attacker-spread degradation curve |
| Leave-one-attack-out, 3 seeds, both datasets | **RQ3** 10 seeds; LwF / DER++ / A-GEM baselines (LwF and DER++ implemented, not yet run) |
| Drift (ADWIN vs schedule), IP-leakage tests | **RQ4** a NetFlow-v2 dataset and 2017 → 2018 transfer (script written, not yet run) |
| Analyst console: live sites, incident queue, dry-run response, gated live teaching | Paper and report |
