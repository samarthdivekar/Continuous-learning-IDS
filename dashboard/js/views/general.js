// Generalisation: leave-one-attack-out (unseen attacks) and the IP-remap leakage test.
import { $, catColor, color, esc, f3, get, int, label, pct, state, table } from "../lib/core.js";
import { mount } from "../lib/charts.js";

let root;
// In leave-one-attack-out every model is trained ONCE, jointly on all other tasks
// (no continual sequence), so the continual-strategy names would mislead.
const LOAO_LABEL = { xgboost_static: "XGBoost", ffnn_naive: "FFNN (per-flow)", gnn_naive: "GNN (graph)" };
const loaoLabel = (m) => LOAO_LABEL[m] || label(m);
export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const { dataset } = state;
  root.innerHTML = `
    <div class="view-head"><div><h2>Generalisation</h2>
      <p><b>Unseen attacks:</b> train on every category except one, then test on the held-out one. <b>IP leakage:</b> scramble host
      identities at test time — a model that memorised attacker IPs would collapse.</p></div>
      <div class="seg" id="gn-mode"><button data-v="binary" class="on">Binary</button><button data-v="multiclass">Multiclass</button></div></div>
    <div class="grid g2">
      <div class="card"><h3>Detection of an attack never seen in training</h3><p class="sub">share of held-out attack flows flagged as any attack · each model trained once, jointly, on all other categories</p>
        <div class="chart tall"><canvas id="gn-loao"></canvas></div></div>
      <div class="card"><h3>Leave-one-attack-out detail</h3><div id="gn-loao-t"></div><div id="gn-callout" style="margin-top:12px"></div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h3>IP-remap leakage test</h3><p class="sub">same trained model scored three ways (after the last task, macro-F1)</p>
        <div class="chart"><canvas id="gn-ip"></canvas></div></div>
      <div class="card"><h3>What the modes mean</h3>
        <p><b>none</b> — normal evaluation.</p>
        <p><b>permute</b> — every host gets a random new identity (bijection). The model has no identity inputs, so this must be exactly invariant.</p>
        <p><b>random_src</b> — every flow gets an independent random source host from a pool of 65,536. The attacker stops being a single hub,
        so this measures how much accuracy comes from host-level structure rather than per-flow behaviour.</p><div id="gn-ip-t"></div></div>
    </div>`;
  const seg = root.querySelectorAll("#gn-mode button");
  seg.forEach((b) => b.addEventListener("click", () => { seg.forEach((x) => x.classList.toggle("on", x === b)); loao(dataset, b.dataset.v); }));
  loao(dataset, "binary");
  ipremap(dataset);
}

async function loao(dataset, mode) {
  let rows;
  try { rows = (await get(`/results/loao?dataset=${dataset}&mode=${mode}`)).rows; }
  catch (e) { $("#gn-loao-t", root).innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const cats = [...new Set(rows.map((r) => r.held_out_category))];
  const models = [...new Set(rows.map((r) => r.model))];
  const val = (c, m) => rows.find((r) => r.held_out_category === c && r.model === m)?.heldout_detection_rate ?? null;
  mount($("#gn-loao", root), { type: "bar", data: { labels: cats, datasets: models.map((m) => ({ label: loaoLabel(m), data: cats.map((c) => val(c, m)),
    backgroundColor: color(m), borderRadius: 5 })) },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true, position: "bottom" },
      tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${pct(c.parsed.y)}` } } },
      scales: { x: { grid: { display: false } }, y: { min: 0, max: 1, ticks: { callback: (v) => pct(v, 0) } } } } });
  $("#gn-loao-t", root).innerHTML = table([
    { title: "Held-out", html: (r) => `<span class="swatch" style="background:${catColor(r.held_out_category)}"></span>${esc(r.held_out_category)}` },
    { title: "Model", value: (r) => loaoLabel(r.model) },
    { title: "Unseen flows", num: true, value: (r) => int(r.n_heldout_flows) },
    { title: "Detected", num: true, value: (r) => pct(r.heldout_detection_rate) },
    { title: "FPR", num: true, value: (r) => pct(r.fpr, 2) },
  ], rows);
  const mean = (m) => { const v = cats.map((c) => val(c, m)).filter((x) => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  $("#gn-callout", root).innerHTML = `<div class="callout">Mean detection of unseen attacks: ${models.map((m) => `<b style="color:${color(m)}">${esc(loaoLabel(m))}</b> ${pct(mean(m))}`).join(" · ")}
    ${cats.length < 7 ? ` <span class="muted">(${cats.length} of 7 categories finished)</span>` : ""}</div>`;
}

async function ipremap(dataset) {
  let r;
  try { r = await get(`/results/ip_remap?dataset=${dataset}&mode=multiclass`); }
  catch (e) { $("#gn-ip-t", root).innerHTML = `<div class="empty" style="margin-top:10px">${esc(e.message)}</div>`; return; }
  const models = [...new Set(r.final.map((x) => x.model))], modes = ["none", "permute", "random_src"];
  const v = (m, k) => r.final.find((x) => x.model === m && x.ip_mode === k)?.macro_f1_seen ?? null;
  mount($("#gn-ip", root), { type: "bar", data: { labels: models.map(label), datasets: modes.map((k, i) => ({ label: k,
    data: models.map((m) => v(m, k)), backgroundColor: models.map((m) => color(m) + ["ff", "aa", "55"][i]), borderRadius: 5 })) },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true, position: "bottom" } },
      scales: { x: { grid: { display: false } }, y: { min: 0, max: 1 } } } });
  $("#gn-ip-t", root).innerHTML = table([{ title: "Model", value: (m) => label(m) },
    ...modes.map((k) => ({ title: k, num: true, value: (m) => f3(v(m, k)) }))], models);
}
