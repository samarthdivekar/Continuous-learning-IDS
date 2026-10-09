# UI audit — Phase 0

Audit of `dashboard/` before the SOC-console upgrade. Everything below was read from the source
(`dashboard/js/views/*.js`, `dashboard/js/lib/*.js`, `dashboard/index.html`) and cross-checked against
sections 6.3–6.10 of the technical documentation.

**Status: awaiting your OK before Phase 1.**

---

## 0 · Two corrections to the brief

**a) The documentation lives at the repository root, not in `docs/`.** The brief points at
`docs/GNN-IDS_Technical_Documentation.pdf`; the file is `GNN-IDS_Technical_Documentation.pdf` at the
root. I have not moved it yet — say the word and I will move it to `docs/` and update the links in
`README.md` and `scripts/docgen/README.md`.

**b) Defect (a) in your list is a documentation defect, not a UI defect.** The control text
`# · ` : ""}` that appears in the PDF is an artifact of the documentation *scanner*, not something a
user ever sees. `explorer.js:63–68` is a correct template literal that renders one button per window:

```js
$("#ex-list", root).innerHTML = rows.map((w) => `
  <button data-w="${w.window_id}" class="${w.window_id === current ? "on" : ""}">
    <span class="num">#${w.window_id}</span>
    <span>${esc(w.task_category)} · ${w.split}${w.top_attack ? ` · <span …>${esc(w.top_attack)}</span>` : ""}
```

My extractor stripped the `${…}` placeholders and printed the leftover punctuation. The window list
renders correctly in the browser (verified). **The fix belongs in `scripts/docgen/extract_ui.py`**, which
should describe generated controls as "one per row" instead of quoting a half-interpolated template. I
will fix the generator in Phase 1 and regenerate the PDF at the end.

---

## 1 · Inventory

### 1.1 Which endpoint feeds which view

| View | Endpoints called | Survives model service down? |
|---|---|---|
| `overview.js` | `/results/continual`, `/results/drift`, `/results/data_summary` | Yes — except the dataset panel, which returns 503 because it imports the ML stack |
| `soc.js` | `/health`, `/windows/catalog`, `/incidents/{w}`, `/incidents/scan`, `/explain/{w}/{e}`, `/incidents/{w}/cef`, `/incidents/{w}/report`, `/actions`, `/actions/{id}/decision` | No (by design) |
| `live.js` | `/demo/start`, `/demo/status`, `/demo/stop`, `/retrain`, `/stream/windows`, `/metrics`, `/drift-status` | No (by design) |
| `explorer.js` | `/health`, `/windows/catalog`, `/graph/{w}` | No (by design) |
| `classify.js` | `/windows/catalog`, `/predict` | No (by design) |
| `compare.js` (Models) | `/results/continual`, `/results/confusion` | Yes |
| `general.js` (Models) | `/results/loao`, `/results/ip_remap` | Yes |
| `drift.js` (Adaptation) | `/results/drift` | Yes |
| `trust.js` (Adaptation) | `/results/open_set`, `/results/conformal`, `/results/incidents`, `/results/adaptation` | Yes |
| `repro.js` | `/results/tuning`, `/results/run_info` | Yes |
| `models.js`, `adapt.js` | none — they are sub-tab containers | n/a |

### 1.2 Controls, by view

Legend for **Name**: ✅ visible `<label>` · ⚠️ `title` only (weak accessible name) · ❌ none.

#### Shell — `index.html`, `main.js`, `lib/tour.js`, `lib/subtabs.js`

| Control | Widget | id | Name | Action |
|---|---|---|---|---|
| CIC-IDS2017 / CSE-CIC-IDS2018 | seg buttons | `ds-seg` | ✅ `aria-label="dataset"` | `setContext({dataset})`, all tabs refresh |
| Multiclass / Binary | seg buttons | `mode-seg` | ✅ `aria-label="label mode"` | `setContext({mode})` |
| Compare models | checkbox | `compare-toggle` | ✅ text | `setContext({compare})` |
| ▶ Tour | button | `tour-btn` | ✅ text | `tour.start()` |
| ? Help | button | `help-btn` | ✅ text | opens drawer |
| ◐ | button | `theme-btn` | ⚠️ `title` only | toggles theme, re-renders charts |
| Close (drawer) | button | `help-close` | ✅ `aria-label` | closes drawer |
| Tour back / next / close | buttons | `tour-prev`, `tour-next`, `tour-x` | ✅ text / ⚠️ ✕ | tour navigation |
| Banner dismiss | button | `banner-x` | ⚠️ `title` only | hides current banner |
| Tab strip (8) | buttons | — (`data-view`) | ✅ text + `title` | hash routing, lazy module load |
| Sub-tabs | seg buttons | `sub-nav-models`, `sub-nav-adapt` | ❌ no group label | mount/activate sub-view |

#### Incident queue — `soc.js`

| Control | Widget | id | Name | Action / endpoint |
|---|---|---|---|---|
| One window / Recent windows | seg buttons | `soc-scope` | ✅ `aria-label="scope"` | switches scope, swaps the two wrappers |
| Traffic window | select | `soc-win` | ✅ "Traffic window" | chooses window |
| Scan the last N windows | select | `soc-limit` | ✅ "Scan the last … windows" | scan size |
| Model | select | `soc-model` | ✅ "Model" | which detector scores |
| Min. confidence | range | `soc-th` | ✅ "Min. confidence" | threshold before grouping |
| Load incidents / Scan windows | button | `soc-go` | ✅ text | `/incidents/{w}` or `/incidents/scan` |
| Category filter | select | `soc-cat` | ⚠️ `title` only | client-side filter |
| Severity filter | select | `soc-sev` | ⚠️ `title` only | client-side filter |
| ⤓ CSV | button | `soc-csv` | ⚠️ `title` only | client-side CSV of visible rows |
| ⤓ CEF | button | `soc-cef` | ⚠️ `title` only | `/incidents/{w}/cef` |
| Incident rows | buttons | generated, one per row | ✅ text | selects incident, loads `/explain` |
| Linux / Windows rule | seg buttons | — | ✅ text | swaps rule text |
| Copy rule | button | `soc-copy` | ✅ text | clipboard |
| Open report | button | `soc-report` | ✅ text | `/incidents/{w}/report` |
| Approve / Reject | buttons | `soc-approve`, `soc-reject` | ✅ text | `POST /actions` then `/actions/{id}/decision` |
| Analyst / note | text inputs | `soc-analyst`, `soc-note` | ⚠️ placeholder only | stored with the decision |
| Log filter | seg buttons | `soc-filter` | ❌ no group label | `/actions?status=` |

#### Live stream — `live.js`

| Control | Widget | id | Name | Action |
|---|---|---|---|---|
| ▶ Start stream | button | `lv-start` | ✅ text | `POST /demo/start` |
| ⟳ Retrain now | button | `lv-retrain` | ✅ text | `POST /retrain` |
| ■ Stop | button | `lv-stop` | ✅ text | `POST /demo/stop` |
| Speed | range | `lv-speed` | ✅ "Speed" | delay per window |

#### Graph explorer — `explorer.js`

| Control | Widget | id | Name | Action |
|---|---|---|---|---|
| Ground truth / Model errors | seg buttons | `ex-mode` | ❌ no group label | recolours edges |
| Task filter | select | `ex-task` | ❌ none | filters window list |
| Split filter | select | `ex-split` | ❌ none | filters window list |
| Model | select | `ex-model` | ❌ none | which model's errors overlay |
| Hosts | range | `ex-nodes` | ✅ "Hosts" | `max_nodes` on `/graph` |
| attacks only | checkbox | `ex-attack` | ✅ text | filters list |
| Window rows | buttons | generated | ✅ text | loads that window |

#### Classify — `classify.js`

| Control | Widget | id | Name | Action |
|---|---|---|---|---|
| Window picker | select | `cl-win` | ❌ none | chooses held-out window |
| Classify window | button | `cl-run-w` | ✅ text | `POST /predict` |
| Classify flows | button | `cl-run-f` | ✅ text | parses CSV, `POST /predict` |
| Load CSV file | file input | `cl-file` | ✅ label text | reads file into textarea (5 MB cap) |
| CSV textarea | textarea | `cl-csv` | ❌ no label | input for pasted flows |

#### Models — `compare.js` + `general.js`

| Control | Widget | id | Name | Action |
|---|---|---|---|---|
| Metric | select | `cmp-metric` | ❌ none | which metric the line chart shows |
| Recall-matrix model | select | `cmp-rm` | ❌ none | heat table model |
| Confusion model / task | selects | `cmp-cm-model`, `cmp-cm-task` | ❌ none | `/results/confusion` |
| Binary / Multiclass | seg buttons | `gn-mode` | ❌ no group label | re-runs the unseen-attack panel |

#### Adaptation & trust — `drift.js` + `trust.js`

| Control | Widget | id | Name | Action |
|---|---|---|---|---|
| Run picker | select | `dr-run` | ❌ none | which stream run to chart |
| Novelty score | select | `tr-method` | ❌ none | energy / softmax / prototype |

#### Reproducibility — `repro.js`

**No interactive controls at all.** Four static panels (λ sweep chart, tuning table, stability ratios,
run metadata). This is the thinnest tab and the one with the most room to improve.

---

## 2 · Defects found

### Severity 1 — wrong or misleading

| # | Where | Problem |
|---|---|---|
| 1.1 | `overview.js` → `/results/data_summary` | The endpoint imports the ML stack, so with the model service down it returns **503 and the Overview dataset panel shows an error** even though Overview is advertised in the outage banner as a tab that still works. The banner's promise and the behaviour disagree. |
| 1.2 | `soc.js` decision log | Times render via `toLocaleString()` on a UTC timestamp, correct, but the column header says only "When" — no timezone shown. On a projector this invites "is that my time?". |
| 1.3 | Docs §6.8–6.10 | Control tables are **empty** for Models, Adaptation & trust and Reproducibility, because the generator pointed at the wrapper modules (`models.js`, `adapt.js`) which hold no controls, and at `repro.js` which genuinely has none. Fix in `scripts/docgen`. |
| 1.4 | `scripts/docgen/extract_ui.py` | Quotes half-interpolated template literals as control labels (the `# · ` : ""}` artifact). |

### Severity 2 — accessibility and keyboard

| # | Where | Problem |
|---|---|---|
| 2.1 | 10 controls | No accessible name: `ex-task`, `ex-split`, `ex-model`, `cl-win`, `cl-csv`, `cmp-metric`, `cmp-rm`, `cmp-cm-model`, `cmp-cm-task`, `dr-run`, `tr-method`. A screen reader announces "combo box" with no clue what it changes. |
| 2.2 | 6 controls | `title`-only names: `soc-cat`, `soc-sev`, `soc-csv`, `soc-cef`, `theme-btn`, `banner-x`. Works, but `title` is not shown on touch and is skipped by some readers. |
| 2.3 | 4 segmented groups | `ex-mode`, `gn-mode`, `soc-filter`, both `sub-nav-*` lack `role="group"` + `aria-label`; the active button is styled but not marked `aria-pressed`. |
| 2.4 | Global | **No visible focus ring** — `:focus-visible` is never styled, so keyboard navigation is invisible. This is the single biggest accessibility gap. |
| 2.5 | Charts | Canvases have no text alternative; the data exists in the adjacent tables, but there is no `aria-describedby` tying them together. |
| 2.6 | Global | No `prefers-reduced-motion` handling; `.pulse`, `fade`, `slide` animations always run. |

### Severity 3 — polish and consistency

| # | Where | Problem |
|---|---|---|
| 3.1 | All tabs | Loading states are a single pulsing line of text, not skeletons; a slow tab looks broken. |
| 3.2 | All tables | No sorting, no sticky header. The decision log and incident tables are the ones that need it. |
| 3.3 | `live.js` | Buttons have no in-flight disabled state; double-clicking Start sends two requests (the API returns 409, which is handled, but the UI flickers). |
| 3.4 | `live.js` | Charts fully re-render each poll instead of pushing points; visible stutter at speed. |
| 3.5 | `explorer.js` | No legend, no "fit to view", no edge click. Hovering gives node info only. |
| 3.6 | `classify.js` | The "missing features are imputed as 0" warning is one line of small text inside a paragraph — easy to miss, and it is exactly the caveat an examiner will ask about. |
| 3.7 | Error states | Every failure renders the same grey box; 404 / 422 / 409 / 503 are not visually distinguished, though the API distinguishes them. |
| 3.8 | Number formatting | `pct()` and `f3()` are used consistently, but raw `toLocaleString()` appears in three places and `fmtValue` only exists in `soc.js`. One helper should own this. |
| 3.9 | Empty states | Wording differs per tab ("Not run yet for this dataset.", "No cluster results.", "no test windows with attacks"). |
| 3.10 | Header at 1366px | Fits in one line (55px) — verified — but the controls wrap at 1200–1280px, which some projectors use. |

### What is already good (keep)

- Per-model colour tokens are used everywhere; a model keeps its colour across tabs.
- Every value rendered through `esc()`; monospace for IPs, rules and paths.
- "Not run yet" empty states already distinguish a 404 from a real error.
- API key is sent as a header, never in a URL (fixed earlier).
- Health polling is cached server-side, so a dead model service does not slow the page.
- Keyboard shortcuts 1–8 / ? / Esc work, and the shell ignores them while typing in a field.

---

## 3 · Proposed plan

**Phase 1 — design system** (`dashboard/css/app.css` → split into `tokens.css`, `base.css`,
`components.css`): rebuilt token layer (keeping every existing model/accent/good/warn/critical hex),
4px spacing scale, type scale, radii, elevation, focus ring, motion tokens; WCAG AA neutrals for both
themes; `:focus-visible` everywhere; `prefers-reduced-motion`; new components (skeleton, error state by
status code, confirm dialog, tooltip, command palette, sortable sticky table, sparkline KPI); presentation
mode. Self-hosted **Inter** + **JetBrains Mono** woff2 in `dashboard/fonts/` — no CSP change.

**Phase 2 — shell**: header reflow to survive 1200px, Ctrl/Cmd+K command palette, `aria` fixes from §2,
status-pill tooltips naming the exact service and port.

**Phase 3 — one commit per tab**, in demo order: Incident queue (three-pane triage + j/k/Enter/a/r/c +
confirm dialogs marked DRY RUN) → Live stream (streaming updates, decimation, disabled states) → Graph
explorer (edge click → `/explain`, legend, fit-to-view) → Overview (hero verdict, cleaner architecture
SVG) → Classify (drag-drop + prominent column-mapping preview) → Models / Adaptation / Reproducibility
(sub-tab ids, small multiples, negative results given equal weight).

**Phase 4 — verification**: both datasets × both label modes × both themes × presentation × compare
on/off × model service stopped; `python -m pytest`; grep for numeric literals in views; Playwright smoke
test if available (it is **not** currently installed — I will provide a manual checklist and, if you want
the automated version, tell me and I will ask before installing anything).

### Questions before I start

1. **Move the PDF to `docs/`?** (brief assumes it is there)
2. **Defect 1.1**: the fix is a UI change (don't call `/results/data_summary` when the model service is
   down, show the "needs model service" state instead). The alternative — making that endpoint not import
   the ML stack — is a backend change, which your constraints forbid. Confirm the UI-side fix is what you want.
3. **Fonts**: Inter + JetBrains Mono, self-hosted. Any preference, or shall I pick?
