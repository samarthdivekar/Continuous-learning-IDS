// SOC queue: a window's alerts grouped into incidents, with a plain-English explanation of
// why each was flagged and a proposed containment action that an analyst approves or rejects.
// Nothing is ever executed — approval is recorded as a dry run.
import { $, $$, catColor, esc, get, int, label, pct, post, prefs, table, toast } from "../lib/core.js";
import { mount } from "../lib/charts.js";

let root, catalog = [], current = null, selected = null;
const NEURAL = ["gnn_ewc_replay", "ffnn_ewc_replay", "gnn_naive"];
const ACTION_TEXT = {
  block_source: "Block the attacking host",
  rate_limit_to_victim: "Rate-limit traffic to the victim",
  isolate_host: "Isolate the host",
  investigate: "Investigate manually",
};

export async function mount_(el) {
  root = el;
  root.innerHTML = `
    <div class="view-head"><div><h2>Incident queue</h2>
      <p>Thousands of flagged flows become a handful of <b>incidents</b> — one per attacker/victim cluster. Pick an incident to see
      <b>why</b> it was flagged and the <b>containment we would propose</b>. You approve or reject; nothing is ever executed.</p></div>
      <span class="tag" id="soc-svc" title="The live model service serves one dataset, independent of the switch above"></span></div>
    <div class="card"><div class="toolbar">
      <label class="inline">Traffic window <select id="soc-win" style="min-width:300px"></select></label>
      <label class="inline">Model <select id="soc-model">${NEURAL.map((m) => `<option value="${m}">${esc(label(m))}</option>`).join("")}</select></label>
      <label class="inline" title="Hide alerts the model is less sure about than this">Min. confidence
        <input type="range" id="soc-th" min="0" max="0.99" step="0.01" value="0"><span id="soc-th-v" class="num">0%</span></label>
      <button class="btn primary" id="soc-go">Load incidents</button>
    </div></div>
    <div class="grid g4" id="soc-kpis" style="margin-top:16px"></div>
    <div class="grid g-5-7" style="margin-top:16px">
      <div class="card"><div class="card-head"><div><h3>Incidents</h3><p class="sub">most severe first · severity = size × confidence</p></div></div>
        <div id="soc-list" class="window-list" style="max-height:640px"><div class="empty">Choose a window and press <b>Load incidents</b>.</div></div></div>
      <div class="card" id="soc-detail"><div class="empty">Select an incident on the left.</div></div>
    </div>
    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Decision log</h3>
      <p class="sub">every proposed action and the analyst's decision · dry run only</p></div>
      <div class="seg" id="soc-filter"><button data-v="" class="on">All</button><button data-v="proposed">Pending</button>
        <button data-v="approved">Approved</button><button data-v="rejected">Rejected</button></div></div>
      <div id="soc-log"></div></div>`;
  get("/health").then((h) => { $("#soc-svc", root).textContent = `live models: ${h.ml?.dataset || "?"} · ${h.ml?.label_mode || ""}`; })
    .catch(() => {});
  try { catalog = (await get("/windows/catalog")).filter((w) => w.split === "test" && w.n_attack > 0); } catch { catalog = []; }
  catalog.sort((a, b) => b.n_attack - a.n_attack);
  $("#soc-win", root).innerHTML = catalog.length ? catalog.map((w) =>
    `<option value="${w.window_id}">#${w.window_id} · ${esc(w.top_attack || w.task_category)} · ${int(w.n_attack)} attack flows</option>`).join("")
    : `<option value="">no test windows with attacks</option>`;
  const th = $("#soc-th", root);
  th.addEventListener("input", () => { $("#soc-th-v", root).textContent = `${Math.round(th.value * 100)}%`; });
  $("#soc-go", root).addEventListener("click", load);
  $$("#soc-filter button", root).forEach((b) => b.addEventListener("click", () => {
    $$("#soc-filter button", root).forEach((x) => x.classList.toggle("on", x === b)); log(b.dataset.v);
  }));
  $("#soc-model", root).value = prefs.get("soc.model", "gnn_ewc_replay");
  log("");
  if (catalog.length) load();
}
export { mount_ as mount };
export const activate = () => log(currentFilter());
export const refresh = () => { if (current) renderList(); };
const currentFilter = () => $("#soc-filter button.on", root)?.dataset.v || "";

async function load() {
  const wid = $("#soc-win", root).value, model = $("#soc-model", root).value, th = $("#soc-th", root).value;
  if (!wid) return;
  prefs.set("soc.model", model);
  $("#soc-list", root).innerHTML = `<div class="empty pulse">Grouping alerts into incidents…</div>`;
  $("#soc-detail", root).innerHTML = `<div class="empty">Select an incident on the left.</div>`;
  try { current = await get(`/incidents/${wid}?model=${model}&threshold=${th}`); }
  catch (e) { $("#soc-list", root).innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  selected = null;
  renderKpis(); renderList();
  if (current.incidents.length) pick(current.incidents[0].incident_id);
}

function kpi(title, value, detail) {
  return `<div class="card kpi"><div class="label">${esc(title)}</div><div class="value num">${value}</div><div class="detail">${detail}</div></div>`;
}
function renderKpis() {
  const c = current, m = c.metrics || {};
  const ratio = c.incidents.length ? c.flagged_flows / c.incidents.length : 0;
  $("#soc-kpis", root).innerHTML = [
    kpi("Flows in window", int(c.n_flows), "network conversations analysed"),
    kpi("Flagged flows", int(c.flagged_flows), `${pct(c.flagged_flows / Math.max(1, c.n_flows))} of the window`),
    kpi("Incidents", int(c.incidents.length), c.incidents.length ? `≈ ${int(Math.round(ratio))} alerts folded into each` : "nothing to review"),
    kpi("Incidents that are real", m.incident_precision == null ? "–" : pct(m.incident_precision, 0),
        `${int(m.true_incidents)} of ${int(m.incidents)} · checked against ground truth (demo only)`),
  ].join("");
}

function sevTag(i) {
  const s = i.severity;
  return s >= 6 ? `<span class="tag bad">critical</span>` : s >= 3 ? `<span class="tag warn">high</span>` : `<span class="tag">low</span>`;
}
function renderList() {
  const list = $("#soc-list", root);
  if (!current.incidents.length) { list.innerHTML = `<div class="empty">No flows above the confidence threshold in this window.</div>`; return; }
  const maxSev = Math.max(...current.incidents.map((i) => i.severity));
  list.innerHTML = current.incidents.map((i) => `
    <button data-id="${i.incident_id}" class="${selected === i.incident_id ? "on" : ""}" style="grid-template-columns:44px 1fr auto">
      <span class="num muted">#${i.incident_id}</span>
      <span><span class="swatch" style="background:${catColor(i.category)}"></span><b>${esc(i.category)}</b>
        · ${i.key_role === "source" ? "from" : "against"} <span class="mono">${esc(i.key_host)}</span>
        <div class="muted" style="font-size:13px">${int(i.n_flows)} flows · ${int(i.n_sources)} source(s) → ${int(i.n_destinations)} destination(s) · ${pct(i.mean_confidence, 0)} confident
          ${i.true_attack_share != null ? (i.true_attack_share > 0.5 ? ` · <span style="color:var(--good)">real attack</span>` : ` · <span style="color:var(--critical)">false alarm</span>`) : ""}</div>
        <div class="bar-mini"><i style="width:${(100 * i.severity / maxSev).toFixed(1)}%"></i></div></span>
      <span>${sevTag(i)}</span>
    </button>`).join("");
  $$("#soc-list button", root).forEach((b) => b.addEventListener("click", () => pick(Number(b.dataset.id))));
}

async function pick(id) {
  selected = id;
  $$("#soc-list button", root).forEach((b) => b.classList.toggle("on", Number(b.dataset.id) === id));
  const i = current.incidents.find((x) => x.incident_id === id);
  const p = i.proposed || {};
  const det = $("#soc-detail", root);
  det.innerHTML = `
    <div class="card-head"><div><h3>Incident #${i.incident_id} · ${esc(i.category)} ${sevTag(i)}</h3>
      <p class="sub">${i.start ? `${esc(i.start.replace("T", " ").slice(0, 19))} → ${esc(i.end.replace("T", " ").slice(11, 19))} · ` : ""}key host <span class="mono">${esc(i.key_host)}</span> (${esc(i.key_role)}, ${int(i.key_host_flows)} flows)</p></div></div>
    <h3 style="font-size:15px;margin-top:6px">Why was this flagged?</h3>
    <div id="soc-why"><div class="empty pulse" style="padding:18px">Explaining a representative flow…</div></div>
    <h3 style="font-size:15px;margin-top:16px">Proposed response <span class="tag">dry run</span></h3>
    <div class="callout"><b>${esc(ACTION_TEXT[p.action] || p.action)}</b> — <span class="mono">${esc(p.target)}</span><br>${esc(p.rationale || "")}</div>
    ${p.rules && (p.rules.linux || p.rules.windows) ? `
      <div class="seg" id="soc-rule-seg" style="margin-top:10px"><button data-v="linux" class="on">Linux (iptables)</button><button data-v="windows">Windows Firewall</button></div>
      <pre class="mono" id="soc-rule" style="white-space:pre-wrap;background:var(--panel-2);border:1px solid var(--border);border-radius:10px;padding:10px;font-size:12.5px;margin:8px 0 0">${esc(p.rules.linux || "")}</pre>` : ""}
    <div class="toolbar" style="margin-top:12px">
      <input type="text" id="soc-analyst" placeholder="your name" value="${esc(prefs.get("analyst", ""))}" style="width:150px" maxlength="64">
      <input type="text" id="soc-note" placeholder="note (optional)" style="flex:1;min-width:140px" maxlength="1000">
      <button class="btn primary" id="soc-approve">Approve</button><button class="btn danger" id="soc-reject">Reject</button>
    </div>
    <p class="note">Approving only records the decision. Connecting approved rules to a real firewall is a deployment choice left to you.</p>`;
  $$("#soc-rule-seg button", det).forEach((b) => b.addEventListener("click", () => {
    $$("#soc-rule-seg button", det).forEach((x) => x.classList.toggle("on", x === b));
    $("#soc-rule", det).textContent = p.rules[b.dataset.v] || "";
  }));
  $("#soc-approve", det).addEventListener("click", () => decide(i, "approve"));
  $("#soc-reject", det).addEventListener("click", () => decide(i, "reject"));
  explain(i);
}

async function explain(i) {
  const why = $("#soc-why", root);
  const edge = (i.sample_edges || [])[0];
  if (edge == null) { why.innerHTML = `<div class="empty">No sample flow available.</div>`; return; }
  let ex;
  try { ex = await get(`/explain/${current.window_id}/${edge}?model=${current.model}`); }
  catch (e) { why.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (selected !== i.incident_id) return;           // user moved on while this was loading
  const st = ex.structure;
  why.innerHTML = `
    <div class="callout">${esc(ex.summary)}</div>
    <div style="margin-top:10px">
      <p class="sub" style="margin-bottom:4px">What in the flow itself pushed the decision (red = towards the verdict, blue = against)</p>
        <div class="chart short"><canvas id="soc-attr"></canvas></div>
      <p class="sub" style="margin:12px 0 4px">Network context</p>
        ${table([{ title: "Fact", key: "k" }, { title: "Value", key: "v", num: true }], [
          { k: "Source host talks to", v: `${int(st.source_distinct_peers)} hosts` },
          { k: "Flows from source", v: int(st.source_flows) },
          ...(st.source_distinct_ports != null ? [{ k: "Distinct ports it targeted", v: int(st.source_distinct_ports) }] : []),
          { k: "Destination hears from", v: `${int(st.destination_distinct_peers)} hosts` },
          { k: "Flows to destination", v: int(st.destination_flows) },
          { k: "Evidence from neighbouring flows", v: pct(ex.context_share, 0) },
        ])}
        <p class="note">Example flow: <span class="mono">${esc(ex.src_ip)} → ${esc(ex.dst_ip)}</span> · model says <b>${esc(ex.predicted_label)}</b>
          (${pct(ex.confidence, 0)}) · ground truth <b>${esc(ex.true_label)}</b></p>
    </div>`;
  const f = ex.features;
  mount($("#soc-attr", root), { type: "bar",
    data: { labels: f.map((x) => x.label), datasets: [{ label: "attribution", data: f.map((x) => x.attribution),
      backgroundColor: f.map((x) => (x.attribution > 0 ? getComputedStyle(document.documentElement).getPropertyValue("--critical") : getComputedStyle(document.documentElement).getPropertyValue("--m-ours"))), borderRadius: 4 }] },
    options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: (c) => { const x = f[c.dataIndex]; return ` value ${x.value == null ? "–" : Number(x.value).toPrecision(4)} · ${x.direction} the verdict`; } } } },
      scales: { x: { grid: { color: getComputedStyle(document.documentElement).getPropertyValue("--grid") }, ticks: { display: false } }, y: { grid: { display: false } } } } });
}

// the database stores UTC; SQLite drops the offset, so treat a bare timestamp as UTC
function localTime(iso) {
  if (!iso) return "–";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

async function decide(i, decision) {
  const btns = [$("#soc-approve", root), $("#soc-reject", root)];
  btns.forEach((b) => { b.disabled = true; });
  const analyst = $("#soc-analyst", root).value.trim() || "analyst";
  prefs.set("analyst", analyst);
  try {
    const a = await post("/actions", { window_id: current.window_id, incident_id: i.incident_id, model: current.model });
    const d = await post(`/actions/${a.id}/decision`, { decision, analyst, note: $("#soc-note", root).value.trim() || null });
    toast(`Incident #${i.incident_id}: ${ACTION_TEXT[d.action] || d.action} ${d.status} (dry run)`);
    btns[0].parentElement.innerHTML = `<span class="tag ${d.status === "approved" ? "good" : "bad"}">${esc(d.status)}</span>
      <span class="muted">by ${esc(d.decided_by)} · ${esc(localTime(d.decided_at))} · recorded in the decision log</span>`;
    log(currentFilter());
  } catch (e) { btns.forEach((b) => { b.disabled = false; }); toast(`Could not record the decision: ${e.message}`); }
}

async function log(status) {
  const el = $("#soc-log", root);
  let rows;
  try { rows = await get(`/actions${status ? `?status=${status}` : ""}`); }
  catch (e) { el.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  if (!rows.length) { el.innerHTML = `<div class="empty">No decisions yet. Approve or reject an incident above.</div>`; return; }
  const tag = (s) => `<span class="tag ${s === "approved" ? "good" : s === "rejected" ? "bad" : "warn"}">${esc(s)}</span>`;
  el.innerHTML = table([
    { title: "When", value: (r) => localTime(r.decided_at || r.created_at) },
    { title: "Window / incident", value: (r) => `#${r.window_id} / ${r.incident_id}` },
    { title: "Category", html: (r) => `<span class="swatch" style="background:${catColor(r.category)}"></span>${esc(r.category)}` },
    { title: "Action", value: (r) => ACTION_TEXT[r.action] || r.action },
    { title: "Target", html: (r) => `<span class="mono">${esc(r.target)}</span>` },
    { title: "Decision", html: (r) => tag(r.status) },
    { title: "By", value: (r) => r.decided_by || "–" },
    { title: "Note", value: (r) => r.note || "" },
  ], rows);
}
