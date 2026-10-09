// Trust & Novelty: can the system notice attacks it was never taught, know when not to decide,
// keep analysts out of alert floods, and adapt safely on a small label budget?
// Every number is read from results/ files written by the experiment scripts.
import { $, attachExport, catColor, color, esc, f3, get, int, label, MODELS, pct, state, table } from "../lib/core.js";
import { barOptions, mount } from "../lib/charts.js";
import { makeSortable, showError } from "../lib/ui.js";
const short = (m) => (MODELS[m] || { short: m }).short;

let root;
const METHOD = { energy: "Energy score", msp: "Max. softmax probability", prototype: "Distance to class prototype" };
// Label budget: only all labels vs the recommended hybrid 100-label setting is shown. The other budget
// variants (pure uncertainty sampling, label-free trigger) are one negative finding, stated in the note.
const ADAPT = {
  drift: "ADWIN, all labels (baseline)",
  drift_al100_hybrid: "ADWIN + 100 labels per update (half least certain, half random)",
  drift_gate: "ADWIN + safety gate (rollback if worse)",
};

export async function mount_(el) { root = el; await render(); }
export { mount_ as mount };
export const refresh = () => render();

async function render() {
  const ds = state.dataset;
  root.innerHTML = `
    <div class="view-head"><div><h2>Trust &amp; novelty</h2>
      <p>Four questions a security team asks before trusting an automated detector. Each panel answers one, using measured results
      (${ds === "cicids2017" ? "CIC-IDS2017" : "CSE-CIC-IDS2018"}, multiclass). Panels 1–3 evaluate the served models, trained
      with seed 42: single run, indicative only.</p></div></div>
    <div class="grid g2">
      <div class="card"><div class="card-head"><div><h3>1 · Does it notice an attack it was never taught?</h3>
        <p class="sub">after each task, the <i>next</i> attack category is still unknown · higher = better at telling “new” from “known” (0.5 = coin flip)</p></div>
        <select id="tr-method" aria-label="novelty score">${Object.entries(METHOD).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
        <div class="chart"><canvas id="tr-os"></canvas></div><div id="tr-os-note"></div></div>
      <div class="card"><h3>Grouping the unknown into candidate new categories</h3>
        <p class="sub">flows flagged as novel are clustered; a pure cluster is a ready-made proposal for a new attack class</p><div id="tr-cl"></div></div>
    </div>
    <div class="grid g2" style="margin-top:16px">
      <div class="card"><h3>2 · Does it know when not to decide?</h3>
        <p class="sub">conformal prediction: when the model is unsure it abstains and hands the flow to a human instead of raising an alarm</p>
        <div class="chart short"><canvas id="tr-cf"></canvas></div><div id="tr-cf-t"></div>
        <p class="note" style="margin-top:10px">This experiment abstains whenever the prediction set is not exactly one class.
        The live system (Live sites) abstains only when the set holds <b>both normal and an attack</b>: on the 2017 test windows
        at α = 0.05 the strict rule raised alarms on 71 % of attack flows (and on 14 % of one recorded DoS window), the live
        rule on 96 % — at the cost of keeping the model's confident false alarms.</p></div>
      <div class="card"><h3>3 · Will analysts drown in alerts?</h3>
        <p class="sub">flagged flows grouped into incidents (connected attacker/victim clusters), at different false-alarm budgets</p><div id="tr-inc"></div></div>
    </div>
    <div class="card" style="margin-top:16px"><h3>4 · Can it adapt safely without labelling everything?</h3>
      <p class="sub">the drift stream re-run with a safety gate (undo an update that makes things worse) and with only a small number of analyst labels per update</p>
      <div id="tr-ad"></div></div>`;
  $("#tr-method", root).addEventListener("change", () => openSet(ds));
  openSet(ds); conformal(ds); incidents(ds); adaptation(ds);
}

const missing = (el, e) => showError(el, e, { what: "this experiment" });

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
  attachExport($("#tr-os", root), { rows: osData.rows, canvas: () => $("#tr-os", root), name: `novelty_${ds}` });
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
  attachExport($("#tr-cf-t", root), { rows, canvas: () => $("#tr-cf", root), name: `conformal_${ds}` });
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
  attachExport($("#tr-inc", root), { rows: r.rows, name: `incidents_${ds}` });
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
  const have = await get("/results/index").catch(() => null);
  if (have && !have?.[ds]?.multiclass?.adaptation) {      // ask only for experiments that exist
    el.innerHTML = `<div class="empty"><span class="title">Not run for this dataset</span>The gated and label-budget
      adaptation variants were run on CIC-IDS2017 only (README §7).</div>`;
    return;
  }
  try { r = await get(`/results/adaptation?dataset=${ds}`); } catch (e) { missing(el, e); return; }
  const rows = [];
  for (const k of Object.keys(ADAPT)) {
    for (const x of r[k] || []) if (x.model === "gnn_ewc_replay" && (k !== "drift" || x.policy === "adwin")) rows.push({ variant: k, ...x });
  }
  attachExport(el, { rows, name: `adaptation_${ds}` });
  el.innerHTML = table([
    { title: "Variant", value: (x) => ADAPT[x.variant] || x.variant },
    { title: "Updates", num: true, value: (x) => int(x.retrains) },
    { title: "Rolled back", num: true, value: (x) => (x.rollbacks == null ? "–" : int(x.rollbacks)) },
    { title: "Labels used", num: true, value: (x) => (!x.label_budget ? "all" : int(x.labels_used)) },
    { title: "Final macro-F1", num: true, value: (x) => f3(x.final_macro_f1_seen) },
    { title: "False-positive rate", num: true, value: (x) => pct(x.final_fpr_seen, 2) },
  ], rows) + `<p class="note">Single run each (seed 42), indicative only. “Labels used” counts flows an analyst would have had to
       label. Spending the same budget only on the least certain flows, or triggering adaptation on confidence instead of
       labelled error, failed: uncertainty sampling never labels a new attack the model confidently mistakes for an
       old one, and because the model stays confident on new attacks, a confidence trigger rarely fires.</p>`;
}
