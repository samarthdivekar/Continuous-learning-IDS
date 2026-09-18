// Drift Analysis: ADWIN vs periodic vs oracle vs never — retrain cost vs final quality, plus timelines.
import { $, color, css, esc, f3, get, int, label, pct, state, table } from "../lib/core.js";
import { barOptions, lineOptions, markerPlugin, modelDataset, mount } from "../lib/charts.js";

let root, d;
const POLICY = { adwin: "ADWIN (drift-triggered)", periodic: "Periodic schedule", oracle: "Oracle (true task boundaries)", never: "Never adapt" };

export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const { dataset } = state;
  root.innerHTML = `
    <div class="view-head"><div><h2>Drift analysis</h2>
      <p>Same model, same stream, four adaptation policies. The brief's efficiency goal is to retrain <b>only</b> when behaviour
      really changes. This page shows how often each policy retrained and what quality it ended with.</p></div></div>
    <div class="grid g2">
      <div class="card"><h3>Retrains vs final macro-F1</h3><p class="sub">bars = retrain cycles · line = final macro-F1 on all tasks seen</p>
        <div class="chart"><canvas id="dr-cost"></canvas></div></div>
      <div class="card"><h3>Policy scoreboard</h3><div id="dr-table"></div><div id="dr-callout" style="margin-top:12px"></div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Error timeline</h3>
      <p class="sub">dashed = adaptation cycles · grey band = true attack share of each window · ▼ = drift flag</p></div>
      <select id="dr-run"></select></div><div class="chart tall"><canvas id="dr-time"></canvas></div></div>
    <div class="card" style="margin-top:16px"><h3>Quality over the stream</h3><p class="sub">macro-F1 on held-out test windows of all tasks seen so far</p>
      <div class="chart"><canvas id="dr-eval"></canvas></div></div>`;
  try { d = await get(`/results/drift?dataset=${dataset}&mode=multiclass`); }
  catch (e) { root.querySelector(".grid").innerHTML = `<div class="card span-2"><div class="empty">${esc(e.message)}</div></div>`; return; }
  const s = d.summary;
  const runs = s.map((r) => `${r.model}|${r.policy}`);
  $("#dr-run", root).innerHTML = runs.map((k) => { const [m, p] = k.split("|"); return `<option value="${k}">${esc(label(m))} · ${esc(POLICY[p] || p)}</option>`; }).join("");
  $("#dr-run", root).addEventListener("change", timeline);
  mount($("#dr-cost", root), { type: "bar", data: { labels: s.map((r) => `${(r.model === "gnn_ewc_replay" ? "Ours" : label(r.model).split(" ")[0])} · ${r.policy}`),
    datasets: [
      { type: "bar", label: "retrains", data: s.map((r) => r.retrains), backgroundColor: s.map((r) => color(r.model)), borderRadius: 6, yAxisID: "y" },
      { type: "line", label: "final macro-F1", data: s.map((r) => r.final_macro_f1_seen), borderColor: css("--ink"), backgroundColor: css("--ink"), yAxisID: "y1", pointRadius: 5 },
    ] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true, position: "bottom" } },
      scales: { x: { grid: { display: false }, ticks: { autoSkip: false, maxRotation: 35 } },
        y: { title: { display: true, text: "retrain cycles" }, grid: { color: css("--grid") }, beginAtZero: true },
        y1: { position: "right", min: 0, max: 1, grid: { display: false }, title: { display: true, text: "final macro-F1" } } } } });
  $("#dr-table", root).innerHTML = table([
    { title: "Model", html: (r) => `<span class="swatch" style="background:${color(r.model)}"></span>${esc(label(r.model))}` },
    { title: "Policy", value: (r) => POLICY[r.policy] || r.policy },
    { title: "Flags", num: true, value: (r) => int(r.drift_flags) },
    { title: "Retrains", num: true, value: (r) => int(r.retrains) },
    { title: "Macro-F1", num: true, value: (r) => f3(r.final_macro_f1_seen) },
    { title: "Retention", num: true, value: (r) => pct(r.final_retention_rate, 0) },
  ], s, { highlight: (r) => r.model === "gnn_ewc_replay" && r.policy === "adwin" });
  const a = s.find((r) => r.model === "gnn_ewc_replay" && r.policy === "adwin");
  const p = s.find((r) => r.model === "gnn_ewc_replay" && r.policy === "periodic");
  const o = s.find((r) => r.model === "gnn_ewc_replay" && r.policy === "oracle");
  const n = s.find((r) => r.model === "gnn_ewc_replay" && r.policy === "never");
  if (a && p && o && n) {
    $("#dr-callout", root).innerHTML = `<div class="callout ${a.retrains > p.retrains ? "warn" : ""}">Adapting matters: without it macro-F1 is
      <b>${f3(n.final_macro_f1_seen)}</b> vs <b>${f3(a.final_macro_f1_seen)}</b> with ADWIN. ADWIN used <b>${a.retrains}</b> retrains where the oracle needed
      <b>${o.retrains}</b> and the periodic schedule <b>${p.retrains}</b>${a.retrains > p.retrains ? " — on this stream it over-triggers relative to a fixed schedule." : "."}</div>`;
  }
  timeline(); evalChart();
}

function timeline() {
  const [m, p] = $("#dr-run", root).value.split("|");
  const w = d.windows.filter((r) => r.model === m && r.policy === p);
  const marks = () => w.filter((r) => r.retrained).map((r) => ({ x: r.stream_index, color: color(m) }));
  const bounds = w.filter((r, i) => i > 0 && r.task_id !== w[i - 1].task_id).map((r) => ({ x: r.stream_index, color: css("--muted"), dash: [], alpha: 0.6, label: `task ${r.task_id + 1}` }));
  mount($("#dr-time", root), { type: "line", plugins: [markerPlugin(() => [...bounds, ...marks()])],
    data: { datasets: [
      { label: "true attack share", data: w.map((r) => ({ x: r.stream_index, y: r.true_attack_fraction })), fill: true, borderWidth: 0, pointRadius: 0, backgroundColor: css("--grid"), stepped: true },
      modelDataset(m, w.map((r) => ({ x: r.stream_index, y: r.error_rate })), { label: "window error", pointRadius: 0 }),
      { label: "drift flag", data: w.filter((r) => r.drift_flag).map((r) => ({ x: r.stream_index, y: r.error_rate })), showLine: false,
        pointStyle: "triangle", rotation: 180, pointRadius: 7, backgroundColor: css("--ink"), borderColor: css("--ink") },
    ] }, options: lineOptions({ yMax: 1, xTitle: "stream window" }) });
}

function evalChart() {
  const keys = [...new Set(d.eval.map((r) => `${r.model}|${r.policy}`))];
  const dash = { adwin: [], periodic: [8, 4], oracle: [2, 3], never: [12, 3, 2, 3] };
  mount($("#dr-eval", root), { type: "line", data: { datasets: keys.map((k) => {
    const [m, p] = k.split("|");
    return modelDataset(m, d.eval.filter((r) => r.model === m && r.policy === p).map((r) => ({ x: Math.max(0, r.stream_index), y: r.macro_f1_seen })),
      { label: `${label(m)} · ${p}`, borderDash: dash[p] || [], pointRadius: 0 });
  }) }, options: { ...lineOptions({ yMax: 1, xTitle: "stream window" }), plugins: { legend: { display: true, position: "bottom" } } } });
}
