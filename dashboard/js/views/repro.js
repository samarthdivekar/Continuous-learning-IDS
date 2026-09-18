// Reproducibility: tuning + λ sweep (validation split), selections, run metadata and seeds.
import { $, esc, f3, get, label, MODELS, pct, state, table } from "../lib/core.js";
const short = (m) => (MODELS[m] || {}).short || m;
import { mount } from "../lib/charts.js";

let root;
export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const { dataset, mode } = state;
  root.innerHTML = `
    <div class="view-head"><div><h2>Reproducibility</h2>
      <p>Every hyper-parameter was chosen on the <b>validation</b> split; test windows were only used by the final runs.
      Re-create every number with <span class="mono">python -m experiments.reproduce_all --dataset ${esc(dataset)}</span>.</p></div></div>
    <div class="grid g2">
      <div class="card"><h3>EWC λ sweep (validation)</h3><p class="sub">final validation macro-F1 per λ · solid γ = 0.9, dashed γ = 1.0 · log x-axis</p>
        <div class="chart"><canvas id="rp-sweep"></canvas></div><div id="rp-selected"></div></div>
      <div class="card"><h3>Training-budget tuning (validation)</h3><div id="rp-tuning"></div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h3>Run metadata</h3><p class="sub">results/${esc(dataset)}/${esc(mode)}/continual/run_info.json</p><div id="rp-info"></div></div>
      <div class="card"><h3>EWC stability (brief trap 3)</h3><p class="sub">max lr·λ·max(F) reached per sweep run — above 1 the penalty step can overshoot</p><div id="rp-stab"></div></div>
    </div>`;
  let t;
  try { t = await get(`/results/tuning?dataset=${dataset}`); } catch (e) { $("#rp-tuning", root).innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  if (t?.sweep) {
    const models = [...new Set(t.sweep.map((r) => r.model))];
    const sets = [];
    for (const m of models) for (const g of [0.9, 1]) {
      const rows = t.sweep.filter((r) => r.model === m && Number(r.gamma) === g && !r.diverged).sort((a, b) => a.lambda - b.lambda);
      sets.push({ label: `${label(m)} γ=${g}`, data: rows.map((r) => ({ x: r.lambda, y: r.val_macro_f1_seen })), borderColor: getColor(m),
        backgroundColor: getColor(m), borderDash: g === 1 ? [6, 4] : [], pointRadius: 4, borderWidth: 2 });
    }
    mount($("#rp-sweep", root), { type: "line", data: { datasets: sets }, options: { responsive: true, maintainAspectRatio: false, parsing: false,
      plugins: { legend: { display: true, position: "bottom", labels: { boxWidth: 18 } } },
      scales: { x: { type: "logarithmic", title: { display: true, text: "λ" } }, y: { min: 0, max: 1 } } } });
    $("#rp-selected", root).innerHTML = `<p class="note">Selected per model: ${Object.entries(t.selected_ewc || {}).map(([m, v]) =>
      `<b>${esc(label(m))}</b> λ=${v.lambda}, γ=${v.gamma}`).join(" · ")}. Neighbouring λ values are often within run-to-run noise.</p>`;
    $("#rp-stab", root).innerHTML = table([
      { title: "Model", value: (r) => short(r.model) }, { title: "γ", num: true, value: (r) => r.gamma },
      { title: "λ", num: true, value: (r) => r.lambda }, { title: "max lr·λ·F", num: true,
        html: (r) => `<span class="${r.max_stability_ratio > 1 ? "tag warn" : ""}">${f3(r.max_stability_ratio)}</span>` },
      { title: "val macro-F1", num: true, value: (r) => f3(r.val_macro_f1_seen) }], t.sweep.slice().sort((a, b) => a.model.localeCompare(b.model) || a.gamma - b.gamma || a.lambda - b.lambda));
  }
  if (t?.tuning) {
    $("#rp-tuning", root).innerHTML = table([
      { title: "Model", value: (r) => short(r.model) }, { title: "Setting", html: (r) => `<span class="mono">${esc(r.overrides)}</span>` },
      { title: "val macro-F1", num: true, value: (r) => f3(r.val_macro_f1_seen) }, { title: "val FPR", num: true, value: (r) => pct(r.val_fpr_seen, 2) }],
      t.tuning, { highlight: (r) => (t.selected_tuning || "").includes(String(r.overrides).split(" ")[0]) });
  }
  try {
    const i = await get(`/results/run_info?dataset=${dataset}&mode=${mode}&experiment=continual`);
    const kv = [["timestamp (UTC)", i.timestamp_utc], ["seed (first run)", i.seed], ["GPU", i.gpu], ["python", i.python],
      ...Object.entries(i.packages || {}).map(([k, v]) => [k, v]), ["processed-data hash", i.data_meta?.cache_key],
      ["flows / windows / features", `${i.data_meta?.n_flows} / ${i.data_meta?.n_windows} / ${i.data_meta?.n_features}`],
      ["command", i.command]];
    $("#rp-info", root).innerHTML = `<table class="data">${kv.map(([k, v]) => `<tr><td class="muted">${esc(k)}</td><td class="mono">${esc(v ?? "–")}</td></tr>`).join("")}</table>`;
  } catch (e) { $("#rp-info", root).innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}

function getColor(m) {
  const v = { gnn_ewc_replay: "--m-ours", ffnn_ewc_replay: "--m-ffnn", gnn_ewc: "--m-gnn-ewc" }[m] || "--muted";
  return getComputedStyle(document.documentElement).getPropertyValue(v).trim();
}
