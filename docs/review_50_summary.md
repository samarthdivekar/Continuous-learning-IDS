# GNN-IDS — 50 % review summary

## Problem

Network intrusion detectors are trained once on known attacks and then either miss new ones or, when retrained
on the new attacks, forget the old ones ("catastrophic forgetting"). Retraining on a fixed schedule wastes effort
when traffic has not changed and reacts late when it has. This project builds a flow-based detector that learns new
attack types one after another without forgetting earlier ones, and retrains only when a drift detector says
behaviour changed.

## Architecture

1. **Flows.** CICFlowMeter flow records from the error-corrected CIC-IDS2017 and CSE-CIC-IDS2018 releases.
2. **Window graph.** Every 5,000 consecutive flows become one graph: hosts are nodes, flows are edges with their
   83 features.
3. **E-GraphSAGE.** An edge-featured GraphSAGE network classifies each flow (edge) using its neighbourhood.
4. **Replay + EWC.** When a new attack type arrives, the model trains on it together with stored windows of earlier
   attacks (replay), with an EWC penalty on weights important to earlier tasks.
5. **ADWIN.** A drift detector watches the model's error stream and triggers retraining only when it changes.

## Results so far

| # | Result | Seeds | README |
|---|---|---|---|
| 1 | Macro-F1 after learning 7 attacks in sequence: **0.964 ± 0.020** (interleaved split) | 3 | §2 |
| 2 | Same on the harder temporal split (train on earlier traffic, test on latest): **0.915 ± 0.031** | 5 | §2 |
| 3 | Retention of the first attack: **1.000** (0.998 temporal); naive retraining: **0** | 3 / 5 | §2 |
| 4 | False-positive rate **0.07 %** of benign flows (interleaved), 0.04 % (temporal) | 3 / 5 | §2 |
| 5 | Graph vs per-flow network, same flows: **+0.036** (interleaved) and **+0.044** (temporal) macro-F1, indicative | 3 / 5 | §2 |
| 6 | CSE-CIC-IDS2018: **0.911 ± 0.042** vs per-flow 0.836 ± 0.029 | 3 | §6 |
| 7 | Attacks never seen in training (2018): graph model catches > 80 % in **8 of 18** runs, per-flow ≤ 0.07 % in all 18; DoS **98.6 %** on all three seeds | 3 | §1 |
| 8 | Randomised source hosts: **0.952 → 0.431** (2017) and 0.922 → 0.729 (2018); per-flow model unaffected | 3 | §5, §6 |
| 9 | Drift stream (2017): adapting ends at ~0.96, never adapting at **0.230** | 3 | §4 |
| 10 | Drift stream (2018): ADWIN uses **23 vs 48** retrains of a fixed schedule at equal quality (0.836 ± 0.117 vs 0.828 ± 0.010) | 3 | §6 |
| 11 | Scoring a 5,000-flow window: **5.5 ms** on the laptop GPU (p50) | 1 machine | §8 |

## Findings, including the negative ones

* **Replay does the work; EWC adds little.** EWC alone fails (0.300, retention 0). Replay alone is within noise
  of EWC + replay on the interleaved split from five stored windows per attack type; on the temporal split EWC
  prevented two replay-only collapses (indicative).
* **The graph depends on host topology.** If each flow gets a random source host, the GNN drops from 0.952 to
  0.431 on 2017 (0.729 on 2018), below the per-flow model, which is unaffected. Lab attacks come from very few
  hosts; real attackers may not.
* **Unseen-attack detection is strong for DoS/DDoS and unstable for BruteForce/Botnet.** DoS 98.6 % on every
  seed; DDoS 99.4 / 82.6 / 67.5 %; BruteForce 99.7 / 0.07 / 100 %; Botnet 8.5 / 84.9 / 11.0 %. Infiltration and
  WebAttack are missed by every model.
* **ADWIN is not cheaper on 2017.** It retrains about twice as often as a fixed schedule (16.7 vs 8); with clean
  attack blocks the schedule also ends higher (0.980 vs 0.960). On 2018 it halves the retrains but only ties on
  quality.
* **The 2018 GNN is seed-sensitive.** Macro-F1 spans 0.863–0.945 across seeds; one run flagged 9,196 benign flows
  as Infiltration.

## Completed vs remaining

| Completed | Remaining (as research questions) |
|---|---|
| ☑ Data pipeline on both error-corrected datasets, label-agnostic 2018 sample | ☐ **RQ1** Does the graph help, or do host statistics suffice? Graph vs per-flow models given per-window host statistics, on seen and unseen attacks |
| ☑ E-GraphSAGE + EWC + replay, all ablations, 3–5 seeds, paired statistics | ☐ **RQ2** Which features are shortcuts? Ablate dst-port / protocol / init-window fields; measure degradation as attackers spread over more hosts |
| ☑ ADWIN drift stream vs periodic / oracle / never, both datasets, 3 seeds | ☐ **RQ3** Is the result robust? 10 seeds, plus LwF, DER++ and A-GEM baselines |
| ☑ Leave-one-attack-out and IP-remap tests, 3 seeds | ☐ **RQ4** Does it transfer? A NetFlow-v2 dataset and CIC-IDS2017 → CSE-CIC-IDS2018 |
| ☑ Product layer: novelty, abstention, incidents, explanations, safety gate | ☐ Paper and final report |
| ☑ Analyst console, live sensor path, cyber-range demo, reproducibility script | |

## Preliminary: host statistics vs graph (RQ1)

**Preliminary — CIC-IDS2017 only, joint training, 3 seeds, XGBoost untuned.** Each flow was given six counts
from its own window (how many flows, hosts and ports its source touches; how many flows and sources its
destination receives; flows per host pair) and the same counts divided by the window size. Details:
`docs/review_50_notes.md`; data: `results/cicids2017/multiclass/context_baseline/`.

* **Seen attacks (same 416,344 test flows):** XGBoost on flow features alone 0.974 macro-F1; with host statistics
  **0.987**; the joint-retrained GNN 0.951 ± 0.015 and FFNN 0.955 ± 0.012.
* **Unseen attacks (leave-one-out):** with host statistics XGBoost catches DoS 97 %, Infiltration 98 %, WebAttack
  100 % and BruteForce 47–90 % on every seed, against 63–68 %, 51–68 %, 8–100 % and ≤ 1 % for the GNN. The GNN is
  ahead only on PortScan (100 % vs 84.5 %).

**Finding:** on this dataset, a tree model with simple window-level host counts matches or beats the graph network
both on seen and on unseen attacks. The graph's measured advantage so far is over a per-flow neural network, not
over host statistics. This has to be repeated on CSE-CIC-IDS2018 and in the continual setting before the README's
claims change, and it is the first thing the second half of the project addresses.
