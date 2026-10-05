// Overview: headline KPIs, the brief's verdict table (computed, with thresholds shown),
// dataset/task timeline and the system architecture.
import { color, esc, f3, get, int, label, modelCell, pct, shownModels, state, table } from "../lib/core.js";
import { barOptions, mount } from "../lib/charts.js";
import { showError, skeleton } from "../lib/ui.js";

let root;
const THRESH = 0.8; // "adapts" / "remembers" pass mark, shown in the UI

export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const { dataset, mode } = state;
  root.innerHTML = `
    <div class="view-head"><div><h2>Mission overview</h2>
      <p>Does the continual GNN learn new attacks <b>and</b> remember old ones? Every number on this page is read from
      <span class="mono">results/${dataset}/${mode}/</span> — nothing is typed in by hand.</p></div></div>
    <div id="ov-plain"></div>
    <div class="grid g4" id="ov-kpis"></div>
    <div class="grid g-7-5" style="margin-top:16px">
      <div class="card"><div class="card-head"><div><h3>The core claim, measured</h3>
        <p class="sub">Adapts = mean recall on each newly learned category; remembers = recall on the first category after the last task.
        ✓ when ≥ ${pct(THRESH, 0)}.</p></div></div><div id="ov-verdict"></div></div>
      <div class="card"><h3>Attack timeline</h3><p class="sub">Chronological tasks — one attack category each (test windows per task).</p>
        <div class="chart" style="height:320px"><canvas id="ov-tasks"></canvas></div></div>
    </div>
    <div class="grid g-8-4" style="margin-top:16px">
      <div class="card"><h3>System architecture</h3><p class="sub">Five layers, run as local processes by scripts/run_stack.ps1.</p>${archSvg()}</div>
      <div class="card"><h3>Dataset</h3><div id="ov-data"></div></div>
    </div>`;
  const kpis = root.querySelector("#ov-kpis");
  kpis.innerHTML = `<div class="card">${skeleton("kpi")}</div>`.repeat(4);
  root.querySelector("#ov-verdict").innerHTML = skeleton("table");
  let c;
  try { c = await get(`/results/continual?dataset=${dataset}&mode=${mode}`); }
  catch (e) {
    kpis.innerHTML = `<div class="card span-2"><div class="empty">No task-sequence results for ${esc(dataset)} / ${esc(mode)} yet (${esc(e.message)}).</div></div>`;
    root.querySelector("#ov-verdict").innerHTML = "";
    await dataPanel(dataset);
    return;
  }
  const last = Math.max(...c.summary.map((r) => r.after_task));
  const fin = Object.fromEntries(c.summary.filter((r) => r.after_task === last).map((r) => [r.model, r]));
  const sd = Object.fromEntries((c.summary_std || []).filter((r) => r.after_task === last).map((r) => [r.model, r]));
  const ours = fin.gnn_ewc_replay || {}, naive = fin.gnn_naive || {}, xgb = fin.xgboost_static || {}, ffnn = fin.ffnn_ewc_replay || {};
  let drift = null;
  try { drift = await get(`/results/drift?dataset=${dataset}&mode=multiclass`); } catch { /* optional */ }
  const adw = drift?.summary.find((r) => r.model === "gnn_ewc_replay" && r.policy === "adwin");
  const orc = drift?.summary.find((r) => r.model === "gnn_ewc_replay" && r.policy === "oracle");
  kpis.innerHTML = [
    tile("Our macro-F1 (all tasks)", f3(ours.macro_f1_seen), sd.gnn_ewc_replay ? `± ${f3(sd.gnn_ewc_replay.macro_f1_seen)} over ${c.seeds.length} seeds` : "",
         `vs FFNN ablation <b>${f3(ffnn.macro_f1_seen)}</b>`),
    tile("Retention of task-1 attack", pct(ours.retention_rate, 0),
         `naive retrain: <span class="${(naive.retention_rate ?? 1) < 0.5 ? "delta-bad" : ""}">${pct(naive.retention_rate, 0)}</span>`, "catastrophic forgetting avoided"),
    tile("False-positive rate", pct(ours.fpr_seen, 2), `benign flows wrongly flagged`, `static XGBoost: ${pct(xgb.fpr_seen, 2)}`),
    adw ? tile("Drift-triggered retrains", int(adw.retrains), `oracle needed ${int(orc?.retrains)}`, `${int(adw.drift_flags)} ADWIN flags · stream of ${int(adw.stream_windows)} windows`)
        : tile("Static baseline blind spot", pct(xgb.macro_f1_seen), "macro-F1 of frozen XGBoost", "never learns new attacks"),
  ].join("");

  const tasks = c.tasks || [];
  const per100k = ours.fpr_seen == null ? null : Math.round(ours.fpr_seen * 100000);
  root.querySelector("#ov-plain").innerHTML = ours.retention_rate == null ? "" : `<div class="callout" style="margin-bottom:16px;font-size:15.5px">
    <b>In plain words:</b> the model learned ${tasks.length} attack types one after another (${tasks.map(esc).join(" → ")}).
    After the last one it still catches <b>${pct(ours.retention_rate, 0)}</b> of the first attack type${naive.retention_rate != null
      ? `, while a normally retrained model catches <b>${pct(naive.retention_rate, 0)}</b>` : ""}.
    ${per100k != null ? `It wrongly flags about <b>${int(per100k)}</b> of every 100,000 normal flows.` : ""}
    New here? Press <span class="kbd">?</span> for a guided tour and glossary.</div>`;

  const order = shownModels(["gnn_ewc_replay", "ffnn_ewc_replay", "gnn_replay", "gnn_ewc", "gnn_naive", "ffnn_naive",
                             "xgboost_static", "gnn_joint", "ffnn_joint"].filter((m) => fin[m]));
  const adapts = (m) => {
    const rows = c.summary.filter((r) => r.model === m && r.after_task > 0);
    return rows.length ? rows.reduce((s, r) => s + (r.current_task_recall ?? 0), 0) / rows.length : null;
  };
  const mark = (v) => (v == null ? "–" : v >= THRESH ? `<span class="tag good">✓ ${pct(v, 0)}</span>` : `<span class="tag bad">✗ ${pct(v, 0)}</span>`);
  root.querySelector("#ov-verdict").innerHTML = table([
    { title: "Model", html: (m) => modelCell(m) },
    { title: "Adapts?", html: (m) => mark(adapts(m)) },
    { title: "Remembers?", html: (m) => mark(fin[m].retention_rate) },
    { title: "Macro-F1", num: true, value: (m) => f3(fin[m].macro_f1_seen) },
    { title: "FPR", num: true, value: (m) => pct(fin[m].fpr_seen, 2) },
  ], order, { highlight: (m) => m === "gnn_ewc_replay" });
  await dataPanel(dataset);
}

async function dataPanel(dataset) {
  const box = root.querySelector("#ov-data");
  let d;
  box.innerHTML = skeleton("lines");
  try { d = await get(`/results/data_summary?dataset=${dataset}`); }
  catch (e) {
    // this is the one Overview panel that needs the model service: it reads the processed-data
    // metadata through the ML stack. Everything else on this page comes from result files.
    showError(box, e, { what: "the dataset panel (it reads processed-data metadata through the model service)" });
    root.querySelector("#ov-tasks")?.closest(".card")?.classList.add("hidden");
    return;
  }
  root.querySelector("#ov-tasks")?.closest(".card")?.classList.remove("hidden");
  box.innerHTML = `
    <div class="grid g2" style="gap:10px;margin:6px 0 12px">
      <div><div class="muted">Flows</div><div style="font-size:26px;font-weight:700">${int(d.n_flows)}</div></div>
      <div><div class="muted">Window graphs</div><div style="font-size:26px;font-weight:700">${int(d.n_windows)}</div></div>
      <div><div class="muted">Edge features</div><div style="font-size:26px;font-weight:700">${int(d.n_features)}</div></div>
      <div><div class="muted">Tasks</div><div style="font-size:26px;font-weight:700">${d.task_categories.length}</div></div>
    </div>
    <p class="note">Error-corrected release (Distrinet / KU Leuven). ${d.flow_sample_fraction < 1 ? `Label-agnostic ${pct(d.flow_sample_fraction, 0)} flow sample.` : "All flows used."}
    IPs define graph topology only — never features.</p>`;
  const tasks = d.task_categories;
  const test = (cat) => d.counts.filter((r) => r.split === "test" && r.category === cat).reduce((s, r) => s + r.flows, 0);
  const benign = (i) => d.counts.filter((r) => r.split === "test" && r.task_id === i && r.category === "Benign").reduce((s, r) => s + r.flows, 0);
  mount(root.querySelector("#ov-tasks"), {
    type: "bar",
    data: { labels: tasks.map((t, i) => `${i + 1}. ${t}`), datasets: [
      { label: "attack flows (test)", data: tasks.map(test), backgroundColor: color("gnn_ewc_replay"), borderRadius: 4 },
      { label: "benign flows (test)", data: tasks.map((_, i) => benign(i)), backgroundColor: getComputedStyle(document.documentElement).getPropertyValue("--benign-edge"), borderRadius: 4 },
    ] },
    options: { ...barOptions({ yMax: null, yFmt: (v) => int(v), horizontal: true, stacked: true }),
               plugins: { legend: { display: true, position: "bottom" } } },
  });
}

function tile(title, value, detail, foot = "") {
  return `<div class="card kpi"><div class="label">${esc(title)}</div><div class="value num">${value}</div>
    <div class="detail">${detail}</div>${foot ? `<div class="note">${foot}</div>` : ""}</div>`;
}

function archSvg() {
  // The request path as it actually runs: the browser only ever talks to 8080, which serves the
  // files and proxies /api; model work is forwarded again to the service that owns the GPU.
  const box = (x, y, w, t, s, hot) => `<rect class="box ${hot ? "hot" : ""}" x="${x}" y="${y}" width="${w}" height="62" rx="12"/>
    <text x="${x + w / 2}" y="${y + 26}" text-anchor="middle">${t}</text>
    <text class="small" x="${x + w / 2}" y="${y + 45}" text-anchor="middle">${s}</text>`;
  const arrow = (d, label, lx, ly) => `<path class="flow" d="${d}"/>` +
    (label ? `<text class="small" x="${lx}" y="${ly}" text-anchor="middle">${label}</text>` : "");
  return `<svg class="arch" viewBox="0 0 980 250" role="img"
      aria-label="Request path: browser to static server on 8080, to the public API on 8000, to the model service on 8001">
    <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M0,0 L10,5 L0,10 z" fill="currentColor" style="color:var(--accent)"/></marker></defs>

    ${box(8, 24, 150, "Browser", "8 tabs · ES modules")}
    ${box(208, 24, 170, "Static server", "8080 · serves + proxies /api")}
    ${box(428, 24, 170, "Public API", "8000 · FastAPI")}
    ${box(648, 24, 180, "Model service", "8001 · GPU · 4 models", true)}
    ${arrow("M158 55 H204", "", 0, 0)}
    ${arrow("M378 55 H424", "/api", 401, 48)}
    ${arrow("M598 55 H644", "forward", 621, 48)}

    ${box(428, 160, 170, "Database", "SQLite / TimescaleDB")}
    ${box(648, 160, 180, "Graph + checkpoint cache", "windows · trained weights")}
    ${box(208, 160, 170, "results/ files", "CSV · JSON · PNG")}
    ${arrow("M513 86 V156")}
    ${arrow("M738 86 V156")}
    <path class="flow" d="M428 110 H300 V156"/>
    <text class="small" x="300" y="128" text-anchor="middle">saved results</text>
  </svg>`;
}

