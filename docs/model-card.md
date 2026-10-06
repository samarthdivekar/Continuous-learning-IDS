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
| CSE-CIC-IDS2018, interleaved split | 3 | 0.881 ± 0.038 | 0.836 ± 0.029 |

* **Retention** of the first attack type after all later tasks: 0.998–1.000 on CIC-IDS2017 (naive retraining: 0).
* **False-positive rate:** 0.04 % (temporal) and 0.07 % (interleaved) of benign flows on CIC-IDS2017.
* **Graph vs per-flow, paired over seeds:** +0.044 (temporal, CI +0.019 to +0.058) and +0.036 (interleaved,
  CI +0.011 to +0.069). Indicative only: with three or five seeds no test can reach conventional significance.
* **Attacks never seen in training** (CSE-CIC-IDS2018, binary, leave-one-attack-out): unseen DoS is detected
  at 98.6 % in both seeds run (per-flow FFNN: 0.1 %); unseen BruteForce at 99.7 % in one seed and 0.0 % in
  the other; DDoS 99.4 % in one seed only.
* **Serving speed** (laptop, GTX 1650): a 5,000-flow window is scored in 5.5 ms on the GPU and 10.5 ms on the
  CPU (p50), about 630,000 and 460,000 flows per second, excluding flow export and graph building.
* **Calibration** (CIC-IDS2017, one run): expected calibration error 0.52 % over all test flows but 2.24 % on
  attack flows, where the model is overconfident (99.4 % mean confidence, 97.7 % accuracy).
* **Not measured:** sensitivity to window size and replay budget (the sweeps are in the README's reproduce
  table).

## Known failure modes

* **Topology dependence.** When each flow's source host is randomised at test time, macro-F1 falls from 0.950
  to 0.427 on CIC-IDS2017 (one run); the per-flow FFNN is unaffected.
* **Seed instability.** Unseen-BruteForce detection flipped from 99.7 % to 0.0 % between two seeds; on
  CSE-CIC-IDS2018 macro-F1 ranges 0.855–0.925 across seeds, and one run flagged 9,196 benign flows as
  Infiltration where an identical run flagged 3.
* **Attacks it does not catch unseen:** Infiltration, WebAttack and mostly Botnet are missed by every model
  when held out.
* **Small classes.** WebAttack has 24 test flows and Botnet 73 on the interleaved CIC-IDS2017 split; their
  per-class numbers move by several points per flow.
* **Drift detection needs labels.** ADWIN watches the labelled error rate; a label-free confidence trigger
  missed most drift. ADWIN over-triggered on CIC-IDS2017 (16 retrains vs 8 periodic) and was more efficient
  than a periodic schedule on CSE-CIC-IDS2018; each is one run.
* **Uncertainty-only active learning fails.** Labelling only the least certain flows never labels a new attack
  the model confidently mistakes for an old one; mixing in random labels fixes it (one run).

## Security and deployment notes

No authentication by default (an API key can be required), no TLS, no rate limiting, no roles. Flows are stored
in clear text in SQLite. Checkpoints are read in PyTorch's weights-only mode and fall back to full unpickling
only for files inside the project's own `cache/` and `results/` (`src/utils/safe_load.py`); cached window
graphs are always unpickled, so those directories must not hold files from elsewhere. The only supported way
to run it is `scripts/run_stack.ps1` on one machine.
