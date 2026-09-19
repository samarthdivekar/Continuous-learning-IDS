// Trust & Novelty: can the system notice attacks it was never taught, know when not to decide,
// keep analysts out of alert floods, and adapt safely on a small label budget?
// Every number is read from results/ files written by the experiment scripts.
import { $, catColor, color, esc, f3, get, int, label, MODELS, pct, state, table } from "../lib/core.js";
import { barOptions, mount } from "../lib/charts.js";
const short = (m) => (MODELS[m] || { short: m }).short;

let root;
const METHOD = { energy: "Energy score", msp: "Max. softmax probability", prototype: "Distance to class prototype" };
const ADAPT = {
  drift: "ADWIN, all labels (baseline)",
  drift_gate: "ADWIN + safety gate (rollback if worse)",
  drift_al100: "ADWIN + 100 labels per update",
  drift_al20: "ADWIN + 20 labels per update",
  drift_al100_hybrid: "ADWIN + 100 labels (half uncertain, half random)",
  drift_labelfree_al100: "Label-free trigger + 100 labels",
};

export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const ds = state.dataset;
  root.innerHTML = `
    <div class="view-head"><div><h2>Trust &amp; novelty</h2>
      <p>Four questions a security team asks before trusting an automated detector. Each panel answers one, using measured results
      (${ds === "cicids2017" ? "CIC-IDS2017" : "CSE-CIC-IDS2018"}, multiclass).</p></div></div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>1 · Does it notice an attack it was never taught?</h3>
        <p class="sub">after each task, the <i>next</i> attack category is still unknown · higher = better at telling “new” from “known” (0.5 = coin flip)</p></div>
        <select id="tr-method">${Object.entries(METHOD).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
        <div class="chart"><canvas id="tr-os"></canvas></div><div id="tr-os-note"></div></div>
      <div class="card"><h3>Grouping the unknown into candidate new categories</h3>
        <p class="sub">flows flagged as novel are clustered; a pure cluster is a ready-made proposal for a new attack class</p><div id="tr-cl"></div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h3>2 · Does it know when not to decide?</h3>
        <p class="sub">conformal prediction: when the model is unsure it abstains and hands the flow to a human instead of raising an alarm</p>
        <div class="chart short"><canvas id="tr-cf"></canvas></div><div id="tr-cf-t"></div></div>
      <div class="card"><h3>3 · Will analysts drown in alerts?</h3>
        <p class="sub">flagged flows grouped into incidents (connected attacker/victim clusters), at different false-alarm budgets</p><div id="tr-inc"></div></div>
    </div>
    <div class="card" style="margin-top:16px"><h3>4 · Can it adapt safely without labelling everything?</h3>
      <p class="sub">the drift stream re-run with a safety gate (undo an update that makes things worse) and with only a small number of analyst labels per update</p>
      <div id="tr-ad"></div></div>`;
  $("#tr-method", root).addEventListener("change", () => openSet(ds));
  openSet(ds); conformal(ds); incidents(ds); adaptation(ds);
}

const missing = (el, e) => { el.innerHTML = `<div class="empty">${e.status === 404 ? "Not run yet for this dataset." : esc(e.message)}</div>`; };

let osData = null;
async function openSet(ds) {
  try { osData = await get(`/results/open_set?dataset=${ds}`); }
  catch (e) { missing($("#tr-os-note", root), e); missing($("#tr-cl", root), e); return; }
  const method = $("#tr-method", root).value;
  const rows = osData.rows.filter((r) => r.method === method);
  const models = [...new Set(rows.map((r) => r.model))];
  const cats = [...new Set(rows.map((r) => r.novel_category))];
  const v = (m, c) => rows.find((r) => r.model === m && r.novel_category === c)?.auroc ?? null;
  mount($("#tr-os", root), { type: "bar", data: { labels: cats.map((c) => `unseen: ${c}`), datasets: models.map((m) => ({
    label: label(m), data: cats.map((c) => v(m, c)), backgroundColor: color(m), borderRadius: 5 })) },
    options: { ...barOptions({ yFmt: f3 }), plugins: { legend: { display: true, position: "bottom" },
      tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: AUROC ${f3(c.parsed.y)}` } } } } });
  const mean = (m) => { const a = cats.map((c) => v(m, c)).filter((x) => x != null); return a.reduce((s, x) => s + x, 0) / a.length; };
  $("#tr-os-note", root).innerHTML = `<div class="callout" style="margin-top:10px">Average AUROC (${esc(METHOD[method])}): ${models.map((m) =>
    `<b style="color:${color(m)}">${esc(label(m))}</b> ${f3(mean(m))}`).join(" · ")}</div>`;
  const cl = osData.clusters.filter((r) => r.model === "gnn_ewc_replay");
  $("#tr-cl", root).innerHTML = cl.length ? table([
    { title: "Unseen category", html: (r) => `<span class="swatch" style="background:${catColor(r.novel_category)}"></span>${esc(r.novel_category)}` },
    { title: "Flagged flows", num: true, value: (r) => int(r.n_flagged) },
    { title: "Clusters", num: true, value: (r) => r.k },
    { title: "Largest cluster is", html: (r) => `<span class="swatch" style="background:${catColor(r.majority_category)}"></span>${esc(r.majority_category)}` },
    { title: "…and is this pure", num: true, value: (r) => pct(r.purity_largest, 0) },
  ], cl, { highlight: (r) => r.majority_category === r.novel_category && r.purity_largest > 0.85 })
    + `<p class="note">Highlighted rows: the largest cluster is almost entirely the new attack — an analyst could label it in one step.
       Where the largest cluster is Benign, the novelty signal was mostly false alarms.</p>`
    : `<div class="empty">No cluster results.</div>`;
}

async function conformal(ds) {
  let r;
  try { r = await get(`/results/conformal?dataset=${ds}`); } catch (e) { missing($("#tr-cf-t", root), e); return; }
  const rows = r.rows;
  const models = [...new Set(rows.map((x) => x.model))];
  const alphas = [...new Set(rows.map((x) => x.alpha))].sort((a, b) => a - b);
  const pick = (m, a) => rows.find((x) => x.model === m && x.alpha === a);
  mount($("#tr-cf", root), { type: "bar", data: { labels: alphas.map((a) => `α = ${a}`), datasets: models.flatMap((m) => [
    { label: `${short(m)} · always decide`, data: alphas.map((a) => pick(m, a)?.false_alarms_argmax ?? null), backgroundColor: color(m) + "55", borderRadius: 4 },
    { label: `${short(m)} · abstain when unsure`, data: alphas.map((a) => pick(m, a)?.false_alarms_after_abstention ?? null), backgroundColor: color(m), borderRadius: 4 }]) },
    options: { ...barOptions({ yMax: null, yFmt: int }), plugins: { legend: { display: true, position: "bottom", labels: { boxWidth: 12 } },
      tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${int(c.parsed.y)} false alarms` } } } } });
  $("#tr-cf-t", root).innerHTML = table([
    { title: "Model", html: (x) => `<span class="swatch" style="background:${color(x.model)}"></span>${esc(short(x.model))}` }, { title: "α", num: true, value: (x) => x.alpha },
    { title: "False alarms → after", num: true, value: (x) => `${int(x.false_alarms_argmax)} → ${int(x.false_alarms_after_abstention)}` },
    { title: "Sent to a human", num: true, value: (x) => pct(x.abstain_rate) },
    { title: "Accuracy when it decides", num: true, value: (x) => pct(x.accuracy_acted, 2) },
  ], rows, { highlight: (x) => x.false_alarms_argmax > 0 && x.false_alarms_after_abstention === 0 })
    + `<p class="note">α is the per-class error rate you are willing to tolerate. A flow is handed off when the model is torn between classes, or when it is less confident than genuine examples of that class usually are. Which α removes the false alarms differs by dataset, so choose it on validation data.</p>`;
}

async function incidents(ds) {
  let r;
  try { r = await get(`/results/incidents?dataset=${ds}`); } catch (e) { missing($("#tr-inc", root), e); return; }
  $("#tr-inc", root).innerHTML = table([
    { title: "Model", html: (x) => `<span class="swatch" style="background:${color(x.model)}"></span>${esc(short(x.model))}` },
    { title: "False-alarm budget", num: true, value: (x) => (x.budget ? `${x.budget}` : "none") },
    { title: "Alerts", num: true, value: (x) => int(x.flow_alerts) },
    { title: "Incidents", num: true, value: (x) => int(x.incidents) },
    { title: "Real incidents", num: true, value: (x) => pct(x.incident_precision, 0) },
    { title: "Attack traffic covered", num: true, value: (x) => pct(x.attack_flows_in_true_incidents, 1) },
  ], r.rows, { highlight: (x) => x.model === "gnn_ewc_replay" && !x.budget })
    + `<p class="note">Every alert is still recorded; incidents are what a person reviews. The budget raises the confidence threshold
       until the false-alarm rate on validation data is within it.</p>`;
}

async function adaptation(ds) {
  const el = $("#tr-ad", root);
  let r;
  try { r = await get(`/results/adaptation?dataset=${ds}`); } catch (e) { missing(el, e); return; }
  const rows = [];
  for (const [k, list] of Object.entries(r)) {
    for (const x of list) if (x.model === "gnn_ewc_replay" && (k !== "drift" || x.policy === "adwin")) rows.push({ variant: k, ...x });
  }
  el.innerHTML = table([
    { title: "Variant", value: (x) => ADAPT[x.variant] || x.variant },
    { title: "Updates", num: true, value: (x) => int(x.retrains) },
    { title: "Rolled back", num: true, value: (x) => (x.rollbacks == null ? "–" : int(x.rollbacks)) },
    { title: "Labels used", num: true, value: (x) => (!x.label_budget ? "all" : int(x.labels_used)) },
    { title: "Final macro-F1", num: true, value: (x) => f3(x.final_macro_f1_seen) },
    { title: "False-positive rate", num: true, value: (x) => pct(x.final_fpr_seen, 2) },
  ], rows) + `<p class="note">Rows appear as each run finishes. “Labels used” counts flows an analyst would have had to label.</p>`;
}
