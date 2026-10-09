# 50 % review — who does what (four presenters)

About 15 minutes: 3 min framing, 8 min live demo (`DEMO.md`), 2 min results and findings, 2 min what's next, then
questions. Names are placeholders: write yours in.

| | Person A | Person B | Person C | Person D |
|---|---|---|---|---|
| Speaks | Problem, architecture, Overview | Incident queue, Live sites sandbox | Drift replay, Graph explorer | Honest results, preliminary finding, next steps |
| Time | ~3.5 min | ~3 min | ~3 min | ~3.5 min |
| Drives the laptop during | A's and D's parts | B's part | C's part | — (holds the summary sheet) |
| Owns in Q&A | "What is new?", "Why a graph?", architecture | false alarms, incidents, "Can it run live?", safety (dry run) | drift, ADWIN cost, forgetting, EWC vs replay | "Why not XGBoost?", topology dependence, unseen attacks, seeds |
| Backup for | D | C | B | A |

Swap the laptop at the boundaries below; whoever speaks clicks, except A also drives for D.

---

## Person A — Problem, architecture, the claim (~3.5 min)

**Material:** `docs/review_50_summary.md` (Problem, Architecture), `DEMO.md` step 1, console **Overview**.

1. Problem in three sentences (from the summary).
2. Architecture, five stages: flows → window graph → E-GraphSAGE → replay + EWC → ADWIN.
3. **Overview** page, then switch **Compare models** on:
   * 0.964 ± 0.020 macro-F1 (interleaved, 3 seeds); 0.915 ± 0.031 on the harder temporal split (5 seeds).
   * First attack still detected (retention 1.000); naive retraining forgets it completely (0).
   * False alarms 0.07 % of benign flows.

Say "3 seeds" / "5 seeds" every time you give a number.

## Person B — What an analyst does (~3 min)

**Material:** `DEMO.md` step 2, `DEMO_FOR_GUIDE.md` Part 1.

1. **Live sites** → choose **DoS** → **▶ Replay into the live view**. Wait ~8 s (first replay warms up).
   A red SANDBOX site appears: ~4,800 of 5,000 flows flagged DoS.
2. **Incident queue** (Source: Live) → open the incident: plain-English "why", evidence bars, network context.
3. **Proposed containment** with the iptables rule. Say: *nothing is executed; a human approves; it is recorded
   as a dry run.*
4. Optional if time: Source **Recorded**, scope **Recent** → many flagged flows folded into a handful of
   incidents. Read the incident count off the screen (it depends on the laptop's checkpoints).

## Person C — It keeps learning, and why a graph (~3 min)

**Material:** `DEMO.md` steps 3–4.

1. **Drift replay** (under Evaluate) → **▶ Start**. Point at the error rising when a new attack arrives, ADWIN
   flagging, the model retraining.
2. Numbers (2017, 3 seeds): never adapting ends at 0.230, adapting at about 0.96. Be honest: with clean attack
   blocks a fixed schedule is better (0.980 vs 0.960) and ADWIN retrains about twice as often; on 2018 ADWIN uses
   half the retrains (23 vs 48) at equal quality.
3. **Graph explorer** → an attack window: a scan fans out, a flood fans in.
4. Unseen attacks (2018, 3 seeds): graph model > 80 % in 8 of 18 held-out runs, per-flow ≤ 0.07 % in all 18;
   DoS 98.6 % on every seed; BruteForce and Botnet swap between seeds.

## Person D — Honest results and what comes next (~3.5 min)

**Material:** `docs/review_50_summary.md` (Findings, Completed vs remaining, Preliminary), `DEMO.md` step 5.

1. Negative findings: EWC alone fails (0.300); replay does the work. Randomised source hosts drop the GNN from
   0.952 to 0.431 (3 seeds); the per-flow model is unaffected. Nobody detects unseen Infiltration on 2018.
2. **Preliminary result (say "preliminary" first):** XGBoost with simple per-window host counts matches or beats
   the graph network on CIC-IDS2017 — 0.987 vs 0.951 on seen attacks, and more of unseen DoS, Infiltration and
   WebAttack. One dataset, joint training, 3 seeds. It sets the first research question of the second half.
3. Completed vs remaining (the checklist), framed as RQ1–RQ4, then paper and report.

---

## Before the review (everyone, 15 min early)

* **B**: start the stack on the demo laptop (Control Center → Start stack, wait for "online – 4 models"), open
  http://localhost:8080, **Live sites → ⟲ Reset model**, do one throw-away DoS replay so the first real one is fast.
* **C**: open Drift replay once, confirm ▶ Start works, then stop it.
* **A**: Overview loaded, Compare models off (turn it on live).
* **D**: `docs/review_50_summary.md` printed or open; backup screenshots in `docs/screens/review_50/` ready in case
  the laptop fails.

## If something breaks

* Console offline → B restarts the stack; meanwhile D shows the backup screenshots and talks through results.
* Replay slow or empty → B moves on to the Recorded incident queue; C covers.
* Drift replay won't start → C shows **Adaptation & trust → Drift & retraining** (saved results) instead.
* Do **not** open the two PDFs in `docs/` — they still show older 2018 numbers (sources fixed, not rebuilt).
