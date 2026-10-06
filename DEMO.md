# Demo script (about 8 minutes)

Start everything with one command, then follow the six steps. Every number below is in
`results/` and on screen — nothing here needs to be said from memory.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_stack.ps1 -Open
```

The ML service takes about a minute to load its models; the dashboard works immediately. If the
model service is down, the console says so in a banner and names the tabs that still work.

---

## 1 · The claim (Overview, 1 min)

> "The model learned seven attack types one after another and still detects the first one perfectly."

* **0.964 ± 0.020** macro-F1 over 3 seeds on the interleaved split, **0.915 ± 0.031** over 5 seeds on the
  harder temporal split (train on each attack's earlier traffic, test on its latest), and ~100 % retention
  of the first attack type on both.
* A normally retrained model: **0 %** retention — it forgets completely.
* False alarms: **0.07 %**, about 66 in every 100,000 normal flows.

The grey line of text under the title says this in plain English; the verdict table below shows
"adapts?" and "remembers?" per model. Turn on **Compare models** to show every baseline.

## 2 · What an analyst does with it (Incident queue, 2 min)

> "A detector that outputs 100,000 alerts is useless. This is the queue a person actually works."

* Press **Load incidents**: ~5,000 flows in the window, **4,986 flagged**, folded into **1 incident**.
* Switch the scope to **Recent windows** → scans 20 windows (~98,000 flows) into **14 incidents**.
* Click an incident: the **plain-English explanation** ("probed 996 different destination ports — a
  port-scan pattern"), the evidence bars, and the network context.
* The **proposed containment** with the exact iptables rule. Say clearly: *nothing is executed; the
  analyst approves and the decision is recorded as a dry run.*
* **Open report** → a printable one-pager (Print → Save as PDF) to attach to a ticket.

## 3 · It keeps learning (Live stream, 2 min)

> "Traffic changes. The system notices and retrains itself."

* Press **Start**. Watch the error rate rise when a new attack appears, ADWIN flag it, and the model
  adapt mid-stream (the feed prints `error 4.7 % → 65.6 % adapted`).
* Headline comparison: ADWIN **16 retrains → 0.949**, a fixed schedule **8 retrains → 0.967**, never
  adapting → **0.232**. Be honest: on 2017 ADWIN over-triggers; on 2018 it wins clearly (24 vs 48).

## 4 · Why a graph (Graph explorer, 1 min)

> "A port scan fans out from one host; a flood fans in to one victim. A per-flow model cannot see that."

* Pick an attack window and show the shape. The **model-error overlay** marks the mistakes.
* The evidence: on 2018, unseen DoS is detected **98.6 %** by the graph model in both seeds run, versus
  **0.1 %** by the per-flow model. Say the other half too: unseen BruteForce was 99.7 % in one seed and
  0.0 % in the other, so the property is real for some attacks and not dependable for all.

## 5 · The honest part (Models → Unseen attacks, Adaptation & trust, 1.5 min)

Examiners reward measured limitations:

* **Randomised source hosts** drop the GNN from 0.950 to **0.427**; the per-flow model is unaffected.
  Training with randomisation recovers **0.914** but costs in-distribution accuracy — a trade-off, not a win.
* **EWC alone fails** (0.300); replay is what prevents forgetting.
* **Uncertainty-only labelling fails** (0.438); half uncertain + half random reaches **0.937** with
  1,700 labels instead of ~100,000.
* **Nobody detects unseen Infiltration** — it looks like normal traffic.

## 6 · It is reproducible (Reproducibility, 0.5 min)

* Every hyper-parameter was chosen on the validation split; test windows were used only by final runs.
* `python -m experiments.reproduce_all --dataset cicids2017` regenerates every number and figure.
* The λ sweep, tuning table and run metadata are all on this tab.

---

## Likely questions

| Question | Answer |
|---|---|
| "Is it better than a commercial NDR?" | Not comparable — this is an evaluated research prototype with dry-run response only. The README says so. |
| "Why not just XGBoost?" | It cannot learn new attack types: 0.231 macro-F1 and it detects 1.3 % of attacks it never saw. |
| "Does the graph really help?" | In distribution, modestly: +0.036 (interleaved, 3 seeds) and +0.044 (temporal, 5 seeds), indicative only. On some attacks never seen in training, clearly: unseen DoS 98.6 % vs 0.1 % in both seeds; unseen BruteForce did not replicate (99.7 % then 0.0 %). |
| "What about false alarms?" | 0.07 % at flow level; abstention removes them entirely at the right α, and incident grouping leaves 50 items with 84 % precision. |
| "Can it run live?" | The stream demo is the live path. A serving benchmark (`experiments/benchmark_serving.py`) is written but could not be run before submission, so there is no measured throughput to quote. |
| "What is new here?" | The combination: continual learning + drift-triggered retraining + an operator-facing layer, evaluated on error-corrected data with negative results reported. |
