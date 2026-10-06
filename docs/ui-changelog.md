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

1. **Fixed in Phase 5.** ~~A backend bug I did not fix (constraint: no changes under `src/`).~~ `DemoRunner` sets `ready = True` when
   the stream warm-starts, and `active_learners()` then serves the demo's models for *every* prediction. `ready`
   is only reset in the exception handler (`src/api/service.py:552`) — not when a run finishes or is stopped. So
   after any Live stream run, the Incident queue, Classify and Graph explorer answer from models warm-started on
   task 1 only, until the service is restarted. Measured: window 363 returned 4,986 flagged flows, then 0 after a
   stream run, then 4,986 again after a restart. The Live stream tab now warns about this; the fix is one line.
2. **Per-flow explanations in the Graph explorer are not possible with the current API.** `/graph` aggregates
   flows per host pair and returns no per-flow index, while `/explain/{window}/{edge}` needs one. Rather than
   invent an endpoint, clicking an edge shows the host-pair facts the payload does carry and points at the
   Incident queue, which has per-flow evidence through `sample_edges`.
3. **Resolved in Phase 5:** `scripts/ui_smoke.py` (Playwright, approved) now covers every page. Playwright is not installed and installing it would add a dependency without
   asking. Verification above was done through the browser with console-error capture on every tab; the manual
   checklist is the Phase 4 table.
4. **Small multiples were not added** to Models and Adaptation & trust. The existing single charts with the
   compare toggle already separate the story models from the full ablation set, and splitting them further
   would have cost more screen than it returned on a projector. Say the word and I will.
5. **The decision log is not paginated.** It shows the most recent 100 actions, which is the API's own default.
6. **Light theme is checked but dark is the designed-for theme**; the demo is expected to run dark.

---

## Phase 5 — defensibility pass

Cuts and fixes made so that what the console shows can be defended. Newest last.

| Change | Why | Where |
|---|---|---|
| **Demo no longer hijacks predictions.** `DemoRunner.ready` is reset when a stream run finishes, is stopped or fails, and cached predictions are dropped, so Classify, the Incident queue and the Graph explorer go back to the checkpoint-loaded models. A regression test fails on the old code. The Live-tab warning banner is removed. | Known limitation 1 above. | `src/api/service.py`, `tests/test_api.py`, `views/live.js` |
| **Classify: paste box removed; incomplete files rejected.** Only file upload remains. The server rejects (HTTP 422) any request whose flows lack one of the 83 trained features, naming them, instead of imputing 0. The panel previews the file (rows, address columns, feature-column count) and says before sending that incomplete files are rejected. Checked in the browser: a 3-feature file is rejected listing the 80 missing features; a complete 40-flow file is classified by all four models. | An imputed verdict looked authoritative and meant nothing. | `views/classify.js`, `src/api/service.py`, `app.py`, `ml_app.py` |
| **Topology-augmented model removed from the console.** `gnn_ewc_replay_topo` is gone from `MODELS` (and its colour token); tables built from results files pass through `known()`, so the IP-remap table that listed it now shows three models. It survives as one README appendix paragraph. | It loses on the main metric; it is a trade-off discussion, not a model a user picks. | `lib/core.js`, `views/general.js`, `css/tokens.css` |
| **Label-budget panel cut to the comparison that matters.** Trust → adaptation shows all labels, the hybrid 100-label setting and the safety gate; the 100- and 20-label uncertainty-only runs and the label-free trigger are one sentence. The panel is labelled single run, indicative only. The API route is unchanged. | Three rows were the same negative finding. | `views/trust.js` |
| **One deployment path.** The architecture card no longer offers Docker Compose; `Dockerfile`, `docker-compose.yml`, `docker/` and `.dockerignore` are deleted and the README says so with the date. | Docker had been verified once and not since; two paths, one maintained. | `views/overview.js`, README |
| **New app shell.** The crowded header and tab strip are replaced by a sidebar (Operate / Evaluate navigation with icons, LIVE badge, service status as four labelled rows, and tour / help / presentation / theme at the bottom) and a slim top bar that holds only the shared context: breadcrumb, dataset, labels, a real Compare-models switch and the command palette. Below 1200px the sidebar becomes an icon rail; below 860px a drawer opened from a menu button, with the page name beside it. Cards, KPI tiles, tables, segmented controls and sub-page tabs (now underline tabs) are restyled. Primary buttons use a darker accent so white text passes AA (4.95:1 dark, 5.54:1 light; measured). Checked in the browser at 1440, 1210, 1100 and 375px wide, dark and light, with no top-bar overflow and no console errors beyond the expected model-service 503s. | The old header packed brand, two toggles, four pills, a switch and four buttons into one row; the user found it cluttered. | `index.html`, `css/*`, `main.js`, `lib/subtabs.js`, `lib/core.js` |
| **Playwright smoke test, and the two bugs it found.** `scripts/ui_smoke.py` loads all 10 pages and sub-pages at 1440 px and iPhone 13 width, dark and light (40 loads), failing on uncaught errors, unexpected console errors, stuck loading states or horizontal overflow. First run found: (1) `dashboard_server.py` crashed on every 404 because its quiet-logging override treated an `HTTPStatus` as a string, so the browser's favicon request got an empty reply on every page; fixed, and the page now carries an inline SVG favicon; (2) on a phone the drift run picker (430 px) and the run-metadata timestamp pushed the page sideways; fixed with `select { max-width: 100% }` and wrapping table cells. Result with the model service down: 40/40 pass. The service-up run waits until PyTorch can load again. | P2.1 | `scripts/ui_smoke.py`, `scripts/dashboard_server.py`, `index.html`, `css/components.css` |
| **Single-seed results say so.** The unseen-attack table shows a Seeds and a Per-seed column when a multi-seed summary exists (2018: BruteForce reads 99.7 % · 0.0 %); drift, IP-remap and the Trust panels read "single run (seed 42), indicative only". The seed comes from the API (`seed`, `seeds` fields on `/results/loao`, `/ip_remap`, `/drift`). | P1.5: a one-seed number must not look like a settled one. | `views/general.js`, `views/drift.js`, `views/trust.js`, `src/api/results.py` |
| **CSE-CIC-IDS2018 binary withdrawn.** With CSE-CIC-IDS2018 selected, the Binary switch is disabled with an explanation, and no route (including the command palette and a stored preference) can select that combination. The binary unseen-attack experiment is unaffected. | D.2: its task sequence had one seed and the extra seeds could not be run. | `lib/core.js`, `main.js` |
