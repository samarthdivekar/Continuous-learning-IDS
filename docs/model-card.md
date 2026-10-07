# Model card: GNN + EWC + replay (continual E-GraphSAGE flow classifier)

## Model

* **Name in code:** `gnn_ewc_replay` (`src/training/learners.py`, `src/models/egraphsage.py`).
* **What it is:** an E-GraphSAGE edge classifier. Every 5,000 consecutive flows become one graph: hosts are
  nodes, flows are edges carrying 83 CICFlowMeter features. Every flow is classified as benign or as one of the
  attack categories learned so far. IP addresses only define the graph; they are never features.
* **How it learns:** attack categories arrive one task at a time. Elastic weight consolidation (λ = 10,
  γ = 0.9, chosen on validation) protects weights that mattered for earlier tasks, and replay rehearses up to
  10 stored windows per attack category, two per training step.
* **Size:** 69,128 parameters.
* **Status:** a final-year research prototype by Samarth. Not maintained as a product.

## Intended use

A triage layer on the flow stream of an IDS a team already runs (see `docs/positioning.md`): grouping
flagged flows into incidents, flagging traffic unlike known attacks, abstaining when unsure, and learning new
attack types without forgetting old ones. Every containment action it proposes is a dry run; a person decides
and acts elsewhere.

## Out of scope

* Blocking or rate-limiting traffic automatically. The system never executes a rule.
* Use as the only detector on a network.
* Networks where attack traffic does not come from a few hosts (NAT, spoofed or highly distributed sources):
  the graph model's accuracy collapses in that case (see failure modes).
* Flows without the full 83-feature set. The API rejects them rather than filling gaps with zeros.
* Any decision about a person.

## Training data

| Dataset | Release | Tasks (in order) | Flows used |
|---|---|---|---|
| CIC-IDS2017 | error-corrected (Engelen et al., 2021) | BruteForce → DoS → WebAttack → Infiltration → Botnet → PortScan → DDoS | all |
| CSE-CIC-IDS2018 | error-corrected (Liu et al., 2022) | BruteForce → DoS → DDoS → WebAttack → Infiltration → Botnet | 15 % label-agnostic sample |

Both are laboratory captures with attacks scheduled in blocks; neither is production traffic.

## Evaluation

All numbers are macro-F1 over test flows of every task seen, after the last task, unless stated. The split
each number comes from is part of the result: *interleaved* tests on windows placed between training windows
of the same session (optimistic); *temporal* trains on each attack's earlier traffic and tests on its latest.

| Setting | Seeds | This model | Per-flow FFNN (same method, no graph) |
|---|---|---|---|
| CIC-IDS2017, temporal split | 5 | **0.915 ± 0.031** (95 % CI 0.888–0.935) | 0.870 ± 0.009 |
| CIC-IDS2017, interleaved split | 3 | 0.964 ± 0.020 | 0.928 ± 0.020 |
| CSE-CIC-IDS2018, interleaved split | 3 | 0.911 ± 0.042 | 0.836 ± 0.029 |

* **Retention** of the first attack type after all later tasks: 0.998–1.000 on CIC-IDS2017 (naive retraining: 0).
* **False-positive rate:** 0.04 % (temporal) and 0.07 % (interleaved) of benign flows on CIC-IDS2017.
* **Graph vs per-flow, paired over seeds:** +0.044 (temporal, CI +0.019 to +0.058) and +0.036 (interleaved,
  CI +0.011 to +0.069). Indicative only: with three or five seeds no test can reach conventional significance.
* **Attacks never seen in training** (CSE-CIC-IDS2018, binary, leave-one-attack-out, two seeds): over 80 % of
  the held-out attack's flows detected in 6 of 12 runs, against at most 0.07 % for the per-flow FFNN. DoS
  (98.6 %, 98.6 %) and DDoS (99.4 %, 82.6 %) replicate; BruteForce (99.7 %, 0.1 %) and Botnet (8.5 %, 84.9 %)
  do not; Infiltration and WebAttack 0 %.
* **Serving speed** (laptop, GTX 1650): a 5,000-flow window is scored in 5.5 ms on the GPU and 10.5 ms on the
  CPU (p50), about 630,000 and 460,000 flows per second, excluding flow export and graph building.
* **Calibration** (CIC-IDS2017, one run): expected calibration error 0.52 % over all test flows but 2.24 % on
  attack flows, where the model is overconfident (99.4 % mean confidence, 97.7 % accuracy).
* **Replay budget** (interleaved split, 3 seeds): replay-only macro-F1 is 0.304 with no stored windows, 0.702
  with one per category and 0.948–0.957 from five upwards; the default is ten.
* **Window size** (interleaved split, 3 seeds): 0.936 at 1,000 flows per window, 0.964 at 5,000 (default)
  and 0.784 at 20,000. The per-flow FFNN scores 0.889, 0.928 and 0.889, so the graph's advantage holds at
  1,000 and reverses at 20,000. Test sets differ between sizes.

## Known failure modes

* **Topology dependence.** When each flow's source host is randomised at test time, macro-F1 falls from 0.952
  to 0.431 on CIC-IDS2017 (3 seeds, every seed 0.427–0.436) and from 0.922 to 0.729 on CSE-CIC-IDS2018
  (3 seeds, 0.690–0.754), below the per-flow FFNN, which is unaffected.
* **Seed instability.** Unseen-attack detection for BruteForce and Botnet swapped between two seeds; on
  CSE-CIC-IDS2018 the identical seed-42 configuration scored 0.855, 0.948 and 0.945 in three trainings, and one run flagged 9,196 benign flows as
  Infiltration where an identical run flagged 3.
* **Attacks it does not catch unseen:** Infiltration, WebAttack and mostly Botnet are missed by every model
  when held out.
* **Large windows drown small attacks.** At 20,000 flows per window the model detects none of the 26
  WebAttack test flows on any seed and no Botnet flows on two of three seeds; keep windows near 5,000.
* **Small classes.** WebAttack has 24 test flows and Botnet 73 on the interleaved CIC-IDS2017 split; their
  per-class numbers move by several points per flow.
* **Drift detection needs labels.** ADWIN watches the labelled error rate; a label-free confidence trigger
  missed most drift. On CIC-IDS2017 (3 seeds) ADWIN retrains about twice as often as a fixed schedule; it ends
  lower when attacks arrive in clean blocks and higher when two attacks are mixed. On CSE-CIC-IDS2018 it
  beat the schedule on cost and quality in one run.
* **Uncertainty-only active learning fails.** Labelling only the least certain flows never labels a new attack
  the model confidently mistakes for an old one; mixing in random labels fixes it (one run).

## Security and deployment notes

No authentication by default (an API key can be required), no TLS, no rate limiting, no roles. Flows are stored
in clear text in SQLite. Checkpoints are read in PyTorch's weights-only mode and fall back to full unpickling
only for files inside the project's own `cache/` and `results/` (`src/utils/safe_load.py`); cached window
graphs are always unpickled, so those directories must not hold files from elsewhere. The only supported way
to run it is `scripts/run_stack.ps1` on one machine.
