# UI changelog — SOC console upgrade

What changed in `dashboard/` across the four phases, what it depends on, and what I deliberately did not do.
The audit that preceded it is in [`ui-audit.md`](ui-audit.md).

---

## Phase 1 — design system

`dashboard/css/app.css` was replaced by three layers. Every class name the views already used was carried
over, so no view broke on the swap.

| File | Holds |
|---|---|
| `css/tokens.css` | every raw value: colour roles, 4px spacing scale, type scale, radii, elevation, focus ring, motion durations, and the light-theme and presentation-mode overrides |
| `css/base.css` | reset, typography, layout primitives, header, tabs, responsive rules |
| `css/components.css` | all components, old and new |

**Contrast was measured, not estimated.** The old `--critical` (`#d03b3b`) **failed WCAG AA at 3.72:1** on dark
panels — the colour used for false alarms, rejected decisions and attack edges. Now `#ef5f5f` (5.5:1). `--muted`
went 5.1 → 6.1:1 and `--good` 5.3 → 7.9:1. All 18 foreground/background pairs pass AA in both themes; the
measured ratios are comments in `tokens.css`.

**Other fixes:** a visible `:focus-visible` ring on every interactive element (there was none at all),
`prefers-reduced-motion` honoured globally, and per-model colour tokens left untouched so a model keeps its
colour everywhere.

**New components:** skeleton loaders, error states keyed to the API's status codes, confirm dialog, tooltip,
command palette, sortable sticky tables, KPI sparkline, busy-button state, drop zone, stacked form field.

**Presentation mode** (⛶ in the header): type ×1.18 and chart strokes 2.2 → 3.4px through tokens, secondary
notes hidden, remembered between visits.

## Phase 2 — shell

* **Command palette** (`Ctrl`/`Cmd`+`K`, `js/lib/palette.js`): 20 actions — all 8 tabs, dataset, label mode,
  compare toggle, start/retrain/stop the stream, theme, presentation mode, help, tour, and "open incident #N"
  from a bare number. Arrow keys, Enter, Escape. Tabs carry concept keywords, so "drift", "novelty",
  "conformal", "triage" find the right tab; a numeric query ranks the incident action first.
* **Header fits one line at 1366px** (it was wrapping to 103px once the presentation button arrived; now 60px).
  Below 1500px the wordmark shortens, status pills collapse to dots with tooltips naming the service and port,
  and Tour/Help become icons. No control is ever removed.
* **Accessibility:** all 11 unnamed selects and the 4 segmented groups got accessible names. Verified by
  querying every tab for inputs without a label, `aria-label` or wrapping label — none remain.

## Phase 3 — per tab

**Incident queue** — rebuilt as three panes (scope and filters · ranked queue · evidence-first detail).
Keyboard triage: `j`/`k` move, `Enter` opens, `a` approve, `r` reject, `c` copy the rule; keys are ignored while
typing or when a dialog owns the keyboard. Approve and reject now go through a confirm dialog carrying a
**DRY RUN** tag, the exact rule, and the sentence "NOT sent to any firewall". Decision log is sortable with
local-time stamps.

**Live stream** — Chart.js decimation (LTTB, 300 samples) and `animation: false`, so a 200-window stream extends
smoothly instead of redrawing; adaptation markers now drawn per model in that model's colour; progress text
("window 29 of 200"); Start/Retrain/Stop disable themselves while a request is in flight; drift events tagged
`retrained` or `refractory period`.

**Graph explorer** — click any edge to select it; the panel shows what `/graph` actually returns for that host
pair (flows, attack flows, category, prediction, misclassified count). Missed attacks and false alarms are now
different colours, both in the legend. Added fit-to-view.

**Overview** — skeletons while loading; the dataset panel degrades honestly if the model stack cannot load; the
architecture diagram redrawn to show the real request path (browser → 8080 → 8000 → 8001) with the saved-results
path branching off.

**Classify** — drag-and-drop CSV, and a **column-mapping preview** that runs before anything is sent: how many
flows, which columns supply the addresses, how many feature columns were found, which columns are ignored, and —
in warning colour — exactly which common features are absent and will be imputed as 0.

**Models · Adaptation & trust · Reproducibility** — status-aware error states everywhere, sortable result
tables, skeletons. Reproducibility gained a copyable reproduce command and a marker on the λ sweep showing the
selected value.

## Phase 4 — verification

| Check | Result |
|---|---|
| 8 tabs × 2 datasets | no console errors |
| 8 tabs × 2 label modes × 2 themes | no console errors |
| Compare models on | 9 model series; off: 3 |
| Presentation mode | type 16 → 18.9px, chart strokes 2.2 → 3.4px |
| Header at 1366px / 1200px | one line, 60px, every control present |
| **Model service stopped** | banner names the affected tabs; Overview, Models, Adaptation & trust and Reproducibility keep rendering from saved results (9/25/26/52 table rows); live tabs show the 503 state |
| Hardcoded metrics | none — the only numeric literals in views are the sample CSV and display thresholds |
| `python -m pytest` | **74 passed** |

## Dependencies

**Added:** none at runtime. Chart.js and d3-force remain the only libraries, still pinned, still from
`cdn.jsdelivr.net`, which the CSP already allows. The CSP in `scripts/dashboard_server.py` is unchanged.

**Fonts:** Inter (400/500/600/700) and JetBrains Mono (400/600), latin subset, self-hosted in
`dashboard/fonts/` — 6 files, 250 KB. Both are SIL Open Font License 1.1. No Google Fonts request is made, so
the console works offline and the CSP stays as it was.

## Known limitations and things I chose not to do

1. **A backend bug I did not fix (constraint: no changes under `src/`).** `DemoRunner` sets `ready = True` when
   the stream warm-starts, and `active_learners()` then serves the demo's models for *every* prediction. `ready`
   is only reset in the exception handler (`src/api/service.py:552`) — not when a run finishes or is stopped. So
   after any Live stream run, the Incident queue, Classify and Graph explorer answer from models warm-started on
   task 1 only, until the service is restarted. Measured: window 363 returned 4,986 flagged flows, then 0 after a
   stream run, then 4,986 again after a restart. The Live stream tab now warns about this; the fix is one line.
2. **Per-flow explanations in the Graph explorer are not possible with the current API.** `/graph` aggregates
   flows per host pair and returns no per-flow index, while `/explain/{window}/{edge}` needs one. Rather than
   invent an endpoint, clicking an edge shows the host-pair facts the payload does carry and points at the
   Incident queue, which has per-flow evidence through `sample_edges`.
3. **No Playwright smoke test.** Playwright is not installed and installing it would add a dependency without
   asking. Verification above was done through the browser with console-error capture on every tab; the manual
   checklist is the Phase 4 table.
4. **Small multiples were not added** to Models and Adaptation & trust. The existing single charts with the
   compare toggle already separate the story models from the full ablation set, and splitting them further
   would have cost more screen than it returned on a projector. Say the word and I will.
5. **The decision log is not paginated.** It shows the most recent 100 actions, which is the API's own default.
6. **Light theme is checked but dark is the designed-for theme**; the demo is expected to run dark.
