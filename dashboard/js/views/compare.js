// Model Comparison: metric-over-tasks for all models, recall heatmap, forgetting, confusion matrix.
import { $, color, esc, f3, get, heatColor, label, MODELS, modelCell, pct, state, table } from "../lib/core.js";
import { barOptions, legend, lineOptions, modelDataset, mount } from "../lib/charts.js";

let root, data, charts = {};
const METRICS = [
  ["macro_f1_seen", "Macro-F1 (tasks seen)"], ["accuracy_seen", "Accuracy (tasks seen)"],
  ["retention_rate", "Retention (task-1 recall)"], ["fpr_seen", "False-positive rate"],
  ["detection_rate_seen", "Detection rate (any attack)"], ["next_task_recall_before_training", "Novel-attack recall (before training)"],
];

export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const { dataset, mode } = state;
  root.innerHTML = `
    <div class="view-head"><div><h2>Model comparison</h2>
      <p>All ${Object.keys(MODELS).length} models through the identical chronological task sequence (${esc(dataset)}, ${esc(mode)}).
      Mean over seeds; the band shows ± 1 std.</p></div>
      <div class="toolbar"><select id="cmp-metric">${METRICS.map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></div></div>
    <div class="card"><div class="card-head"><div><h3 id="cmp-title"></h3><p class="sub">x = after training task k</p></div>
      <div class="legend" id="cmp-legend"></div></div><div class="chart tall"><canvas id="cmp-line"></canvas></div></div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><div><h3>Per-category recall matrix</h3><p class="sub">row = after task i · column = category evaluated</p></div>
        <select id="cmp-rm"></select></div><div id="cmp-heat"></div></div>
      <div class="card"><h3>Forgetting</h3><p class="sub">Backward transfer (BWT) — negative = forgetting. Closer to 0 is better.</p>
        <div class="chart"><canvas id="cmp-bwt"></canvas></div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><div class="card-head"><div><h3>Confusion matrix</h3><p class="sub">test windows of all tasks seen · seed 42</p></div>
        <div class="toolbar"><select id="cmp-cm-model"></select><select id="cmp-cm-task"></select></div></div><div id="cmp-cm"></div></div>
      <div class="card"><h3>Final scoreboard</h3><p class="sub">after the last task</p><div id="cmp-table"></div></div>
    </div>`;
  try { data = await get(`/results/continual?dataset=${dataset}&mode=${mode}`); }
  catch (e) { root.querySelector(".card").innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const models = data.models;
  $("#cmp-rm", root).innerHTML = models.map((m) => `<option value="${m}">${esc(label(m))}</option>`).join("");
  $("#cmp-cm-model", root).innerHTML = $("#cmp-rm", root).innerHTML;
  $("#cmp-cm-task", root).innerHTML = data.tasks.map((t, i) => `<option value="${i}" ${i === data.tasks.length - 1 ? "selected" : ""}>after ${i + 1}. ${esc(t)}</option>`).join("");
  $("#cmp-metric", root).addEventListener("change", drawLine);
  $("#cmp-rm", root).addEventListener("change", drawHeat);
  $("#cmp-cm-model", root).addEventListener("change", drawCm);
  $("#cmp-cm-task", root).addEventListener("change", drawCm);
  charts.line = mount($("#cmp-line", root), { type: "line", data: { datasets: [] }, options: lineOptions({ xTitle: "after task" }) });
  legend($("#cmp-legend", root), models, () => [charts.line]);
  drawLine(); drawHeat(); drawBwt(); drawCm(); drawTable();
}

function drawLine() {
  const key = $("#cmp-metric", root).value;
  $("#cmp-title", root).textContent = METRICS.find(([k]) => k === key)[1];
  const fpr = key === "fpr_seen";
  const std = new Map((data.summary_std || []).map((r) => [`${r.model}|${r.after_task}`, r[key]]));
  const sets = [];
  for (const m of data.models) {
    const rows = data.summary.filter((r) => r.model === m && r[key] != null).sort((a, b) => a.after_task - b.after_task);
    const pts = rows.map((r) => ({ x: r.after_task + 1, y: r[key] }));
    if (!pts.length) continue;
    const band = rows.map((r) => std.get(`${m}|${r.after_task}`) || 0);
    sets.push({ ...modelDataset(m, pts.map((p, i) => ({ x: p.x, y: p.y + band[i] }))), label: `${label(m)} +σ`, borderWidth: 0, pointRadius: 0,
                backgroundColor: color(m) + "22", fill: "+1" });
    sets.push(modelDataset(m, pts.map((p, i) => ({ x: p.x, y: Math.max(0, p.y - band[i]) })), { label: `${label(m)} −σ`, borderWidth: 0, pointRadius: 0, fill: false }));
    sets.push(modelDataset(m, pts));
  }
  charts.line.data.datasets = sets;
  charts.line.options = lineOptions({ yMax: fpr ? null : 1, xTitle: "after training task",
    xTicks: { stepSize: 1, callback: (v) => `${v}. ${data.tasks[v - 1] || ""}` } });
  charts.line.options.plugins.tooltip.filter = (i) => !/σ$/.test(i.dataset.label);
  charts.line.update();
}

function drawHeat() {
  const m = $("#cmp-rm", root).value, R = data.recall_matrix[m];
  if (!R) { $("#cmp-heat", root).innerHTML = `<div class="empty">no matrix</div>`; return; }
  const cols = R.cols.map((c) => c.split("_").slice(1).join("_"));
  $("#cmp-heat", root).innerHTML = `<div class="table-wrap"><table class="data heat"><thead><tr><th></th>${cols.map((c) => `<th class="num">${esc(c)}</th>`).join("")}</tr></thead>
    <tbody>${R.values.map((row, i) => `<tr><th>after ${i + 1}</th>${row.map((v, j) =>
      `<td class="cell" style="background:${j <= i ? heatColor(v) : "transparent"};${j > i ? "color:var(--muted)" : ""}" title="${esc(cols[j])} after task ${i + 1}: ${f3(v)}">${v == null ? "–" : v.toFixed(2)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <p class="note">Upper-right cells are categories not yet trained on (greyed). Diagonal = learning; below = remembering.</p>`;
}

function drawBwt() {
  const ms = data.models.filter((m) => data.forgetting[m]);
  mount($("#cmp-bwt", root), { type: "bar",
    data: { labels: ms.map((m) => (MODELS[m] || {}).short || m), datasets: [{ label: "BWT", data: ms.map((m) => data.forgetting[m].bwt),
      backgroundColor: ms.map((m) => color(m)), borderRadius: 6 }] },
    options: { ...barOptions({ yMax: 0.1, yFmt: (v) => Number(v).toFixed(2) }), scales: { ...barOptions().scales,
      y: { min: -1, max: 0.1, grid: { color: getComputedStyle(document.documentElement).getPropertyValue("--grid") }, ticks: { callback: (v) => v.toFixed(1) } } } } });
}

async function drawCm() {
  const m = $("#cmp-cm-model", root).value, t = $("#cmp-cm-task", root).value;
  const box = $("#cmp-cm", root);
  try {
    const cm = await get(`/results/confusion?dataset=${state.dataset}&mode=${state.mode}&model=${m}&after_task=${t}`);
    const rowSum = cm.matrix.map((r) => r.reduce((a, b) => a + b, 0));
    const keep = cm.labels.map((_, i) => rowSum[i] > 0 || cm.matrix.some((r) => r[i] > 0));
    const L = cm.labels.filter((_, i) => keep[i]);
    box.innerHTML = `<div class="table-wrap"><table class="data heat"><thead><tr><th>true \\ pred</th>${L.map((l) => `<th class="num">${esc(l)}</th>`).join("")}</tr></thead>
      <tbody>${cm.matrix.map((row, i) => keep[i] ? `<tr><th>${esc(cm.labels[i])}</th>${row.filter((_, j) => keep[j]).map((v, jj) => {
        const j = cm.labels.indexOf(L[jj]); const share = rowSum[i] ? v / rowSum[i] : 0;
        return `<td class="cell" style="background:${i === j ? heatColor(share) : share > 0.01 ? `color-mix(in srgb, var(--critical) ${Math.round(Math.min(1, share * 3) * 70)}%, transparent)` : "transparent"}"
          title="${(share * 100).toFixed(2)}% of true ${esc(cm.labels[i])}">${v.toLocaleString()}</td>`; }).join("")}</tr>` : "").join("")}</tbody></table></div>
      <p class="note">Blue diagonal = correct share of each true class; red off-diagonal = confusions (≥ 1% of the row).</p>`;
  } catch (e) { box.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

function drawTable() {
  const last = Math.max(...data.summary.map((r) => r.after_task));
  const rows = data.summary.filter((r) => r.after_task === last).sort((a, b) => (b.macro_f1_seen ?? 0) - (a.macro_f1_seen ?? 0));
  $("#cmp-table", root).innerHTML = table([
    { title: "Model", html: (r) => modelCell(r.model) },
    { title: "Macro-F1", num: true, value: (r) => f3(r.macro_f1_seen) },
    { title: "Accuracy", num: true, value: (r) => f3(r.accuracy_seen) },
    { title: "Retention", num: true, value: (r) => pct(r.retention_rate, 0) },
    { title: "FPR", num: true, value: (r) => pct(r.fpr_seen, 2) },
    { title: "Seeds", num: true, value: (r) => r.n_seeds ?? "–" },
  ], rows, { highlight: (r) => r.model === "gnn_ewc_replay" });
}
