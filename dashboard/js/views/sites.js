// Live sites: real traffic from sensor machines (src/live). Each sensor uploads short capture chunks;
// the server converts them with the pinned CICFlowMeter, scores them with the live model and files them
// per site. Here you watch per-site traffic, triage incidents (dry-run rules), label flows and adapt the
// model without forgetting. Distinct from "Drift replay", which replays the recorded dataset.
import { catColor, esc, get, int, openApi, pct, post, toast } from "../lib/core.js";
import { GraphView } from "../lib/graphview.js";
import { withBusy } from "../lib/ui.js";

let root, timer, sel = null, teachSel, incSig = "", gview, gWindow = null;

const CLASSES = ["Benign", "BruteForce", "DoS", "WebAttack", "Infiltration", "Botnet", "PortScan", "DDoS"];

export async function mount(el) {
  root = el;
  const stepNum = (n) => `<span style="display:inline-grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--accent);color:#fff;font-size:13px;font-weight:700;margin-right:9px;vertical-align:middle">${n}</span>`;
  root.innerHTML = `
    <div class="view-head"><div><h2>Live sites</h2>
      <p>Watch traffic get scored by the model in real time, then teach it. Follow the three steps below.
      Nothing is ever blocked — proposed actions are a dry run.</p></div>
      <div class="toolbar">
        <button class="btn" id="st-reset" title="Forget live learning and go back to the trained model">⟲ Reset model</button>
      </div></div>

    <div class="card" id="st-step1" style="margin-bottom:16px">
      <div class="card-head"><div><h3>${stepNum(1)}Get traffic in</h3>
        <p class="sub">pick any source — the easiest is the sandbox replay (safe, nothing real is attacked)</p></div></div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:4px">
        <label class="inline">Replay a recorded attack:
          <select id="st-replay-cat" aria-label="recorded attack to replay">
            <option>DoS</option><option>PortScan</option><option>DDoS</option>
            <option>BruteForce</option><option>Infiltration</option><option>Botnet</option></select></label>
        <button class="btn primary" id="st-replay" title="Feed a real recorded window of this attack through the live scorer">▶ Replay into the live view</button>
      </div>
      <p class="note" style="margin-top:12px"><b>Other sources:</b> run the <b>cyber range</b> in the desktop app (isolated containers: office traffic and an attacker, streamed live),
        or start a sensor on a machine: <span class="mono">python sensor/agent.py --server http://THIS-PC:8000 --site home --iface &lt;n&gt;</span></p>
      <div id="st-nosites" class="empty" style="margin-top:10px"><span class="title">No traffic yet</span>Replay an attack above (or run the cyber range) and it appears below within a few seconds.</div>
    </div>

    <section id="st-step2" class="hidden" style="margin-bottom:16px">
      <h3 style="margin:0 0 4px">${stepNum(2)}Watch it scored</h3>
      <p class="sub" style="margin:0 0 12px">each source is a <b>site</b>; a red number means the model flagged attacks there</p>
      <div id="st-sites" class="grid g4" style="margin-bottom:16px"></div>
      <div class="card" id="st-graphcard">
        <div class="card-head"><div><h3 id="st-gtitle">Live traffic graph</h3>
          <p class="sub" id="st-gsub">hosts are dots, flows are lines; red = the model predicts an attack. Scroll to zoom, drag to pan, hover a host.</p></div>
          <div class="toolbar"><button class="icon-btn small" id="st-gfit" title="Fit the graph">⤢ Fit</button></div></div>
        <div class="graph-stage" id="st-gstage" style="height:340px"></div>
        <div class="legend" id="st-glegend" style="margin-top:10px"></div></div>
    </section>

    <section id="st-step3" class="hidden">
      <h3 style="margin:0 0 4px">${stepNum(3)}Review &amp; teach</h3>
      <p class="sub" style="margin:0 0 12px">triage the incidents, then label traffic and adapt — the model learns without forgetting</p>
      <div class="card" id="st-model" style="margin-bottom:16px"></div>
      <div class="grid g-8-4">
        <div class="card"><div class="card-head"><div><h3>Incidents <span id="st-scope" class="muted"></span></h3>
          <p class="sub">confident attack verdicts of the last 15 minutes, grouped by attacker/victim within each site; each carries a dry-run rule.
          Approvals and rejections go to the decision log in the <a href="#soc">Incident queue</a>.</p></div>
          <div class="toolbar"><button class="icon-btn small" id="st-cef" title="Download these incidents for a SIEM (ArcSight CEF)">⤓ CEF</button></div></div>
          <div id="st-incidents"></div></div>
        <div class="grid" style="gap:16px">
          <div class="card"><h3>Unsure — needs an analyst</h3><p class="sub">the model could not tell attack from normal (its calibrated prediction set held both), so no alarm was raised</p>
            <div id="st-unsure"></div></div>
          <div class="card"><h3>Unfamiliar traffic</h3><p class="sub">called benign but unlike anything seen in training — candidates for a new attack</p>
            <div id="st-unfamiliar"></div></div>
          <div class="card"><h3>Teach the model</h3>
            <p class="sub">label recent traffic, then adapt. Adaptation is gated: if it would forget old attacks, it is rolled back.</p>
            <div id="st-teach"></div></div>
        </div>
      </div>
    </section>`;
  root.querySelector("#st-reset").addEventListener("click", (e) =>
    withBusy(e.target, async () => { try { const r = await post("/live/reset"); toast(`model reset to v${r.version}`); await tick(); } catch (err) { toast(err.message); } }));
  root.querySelector("#st-replay").addEventListener("click", (e) => withBusy(e.target, async () => {
    const category = root.querySelector("#st-replay-cat").value;
    try {
      const r = await post("/sensor/replay_recorded", { category, site: "sandbox" });
      const flagged = r.counts ? Object.entries(r.counts).filter(([k]) => k !== "Benign").map(([k, v]) => `${v} ${k}`).join(", ") : "";
      toast(`Replayed ${r.replayed} recorded ${category} flows → ${flagged || "all benign"}`);
      sel = "sandbox"; gWindow = null; await tick();
    } catch (err) { toast(err.message); }
  }));
  root.querySelector("#st-cef").addEventListener("click", () =>
    openApi(`/live/incidents/cef?minutes=15${sel ? `&site=${encodeURIComponent(sel)}` : ""}`,
            { filename: `live_incidents_${sel || "all"}.cef` }));
  gview = new GraphView(root.querySelector("#st-gstage"));
  root.querySelector("#st-gfit").addEventListener("click", () => gview.fit());
  await tick();
  timer = setInterval(tick, 2000);
}

export function refresh() { tick(); }
export function activate() { tick(); }

async function tick() {
  if (!root || !root.isConnected) { clearInterval(timer); return; }
  let sites;
  try { sites = (await get("/live/sites")).sites; } catch { return; }
  const hasData = sites.length > 0;
  // Steps 2 and 3 stay hidden until some traffic arrives, so an empty tab is one clear call to action
  // instead of a wall of empty panels.
  root.querySelector("#st-nosites").style.display = hasData ? "none" : "";
  root.querySelector("#st-step2").classList.toggle("hidden", !hasData);
  root.querySelector("#st-step3").classList.toggle("hidden", !hasData);
  if (!hasData) return;
  renderSites(sites);
  if (sel && !sites.some((s) => s.site === sel)) sel = null;
  if (!sel && sites.length) sel = sites[0].site;
  root.querySelector("#st-scope").textContent = sel ? `· ${sel}` : "· all sites";

  const badge = document.querySelector("#sites-badge");
  if (badge) badge.classList.toggle("hidden", !sites.some((s) => s.online && s.flows_5min));

  await renderModel();
  await renderDrift();
  const q = sel ? `site=${encodeURIComponent(sel)}&windows=200&minutes=15` : "windows=200&minutes=15";
  const inc = await get(`/live/incidents?${q}`).catch(() => null);
  if (inc) {
    // re-render the incident list only when it actually changed, so clicks/scroll are not interrupted
    const sig = JSON.stringify([sel, inc.n_flows, inc.incidents.map((i) => [i.category, i.key_host, i.n_flows, i.record?.status]),
      inc.unfamiliar.map((u) => [u.host, u.flows]), (inc.unsure || []).map((u) => [u.host, u.flows])]);
    if (sig !== incSig) { incSig = sig; renderIncidents(inc); renderUnfamiliar(inc.unfamiliar); renderUnsure(inc.unsure || []); }
  }
  // the teach panel has a text input; rebuild it only when the selected site changes
  if (sel !== teachSel) { teachSel = sel; renderTeach(sel); gWindow = null; }
  await renderGraph();
}

async function renderGraph() {
  // show the most recent non-empty window of the selected site, reloading only when a newer one arrives
  const q = sel ? `?site=${encodeURIComponent(sel)}&limit=8` : "?limit=8";
  const w = await get(`/live/windows${q}`).catch(() => null);
  const latest = w && [...w.windows].reverse().find((x) => x.n_flows > 0);
  if (!latest) {
    if (gWindow !== "none") { gWindow = "none"; gview.setData({ nodes: [], edges: [] });
      root.querySelector("#st-gsub").textContent = "waiting for traffic from this site…";
      root.querySelector("#st-glegend").innerHTML = ""; }
    return;
  }
  if (latest.window_id === gWindow) return;
  gWindow = latest.window_id;
  // the site's last two minutes: the same span each chunk is scored in (one chunk alone is a few flows)
  const g = await get(`/live/site_graph?site=${encodeURIComponent(latest.site)}&seconds=120`).catch(() => null);
  if (!g || gWindow !== latest.window_id) return;
  gview.mode = "truth";
  gview.setData(g);
  const age = latest.received_at ? Math.max(0, Math.round((Date.now() - Date.parse(latest.received_at)) / 1000)) : null;
  root.querySelector("#st-gtitle").textContent = `Live traffic graph · ${esc(latest.site)}`;
  root.querySelector("#st-gsub").innerHTML = `last 2 min · ${int(g.n_nodes)} hosts, ${int(g.n_edges)} flows · ${int(g.n_attack_edges)} predicted attack` +
    (g.truncated ? ` · showing the busiest ${g.nodes.length} hosts` : "") +
    (age != null ? ` · newest chunk ${age}s ago` : "");
  const cats = Object.entries(g.category_counts || {});
  root.querySelector("#st-glegend").innerHTML = (cats.length
    ? cats.map(([c, v]) => `<span class="item" style="cursor:default"><i class="line" style="background:${catColor(c)}"></i>${esc(c)} <span class="muted num">${int(v)}</span></span>`).join("")
    : `<span class="item" style="cursor:default"><i class="line" style="background:var(--benign-edge)"></i>all benign</span>`)
    + `<span class="item" style="cursor:default"><i class="line" style="background:var(--critical);height:10px;width:10px;border-radius:50%"></i>host in a predicted attack</span>`;
}

function renderSites(sites) {
  root.querySelector("#st-sites").innerHTML = sites.map((s) => {
    const on = s.site === sel;
    const alert = s.flagged_5min > 0;
    return `<button class="card kpi site-card${on ? " hl" : ""}" data-site="${esc(s.site)}" style="text-align:left;cursor:pointer;border-color:${alert ? "var(--critical)" : on ? "var(--accent)" : ""}">
      <div class="label" style="display:flex;align-items:center;gap:6px">
        <span class="dot" style="background:${s.online ? "var(--good)" : "var(--muted)"};width:8px;height:8px;border-radius:50%;display:inline-block"></span>
        ${esc(s.site)}</div>
      <div class="value num" style="font-size:26px;color:${alert ? "var(--critical)" : "var(--ink)"}">${int(s.flagged_5min)}</div>
      <div class="note">flagged / 5 min · ${int(s.flows_5min)} flows · ${s.online ? "online" : `${int(s.seconds_since)}s ago`}${s.unsure_5min ? ` · <span style="color:var(--warn)">${int(s.unsure_5min)} unsure</span>` : ""}${s.unfamiliar_5min ? ` · <span style="color:var(--warn)">${int(s.unfamiliar_5min)} unfamiliar</span>` : ""}</div>
    </button>`;
  }).join("");
  root.querySelectorAll(".site-card").forEach((b) => b.addEventListener("click", () => { sel = b.dataset.site; tick(); }));
}

async function renderModel() {
  const m = await get("/live/model").catch(() => null);
  const el = root.querySelector("#st-model");
  if (!m) { el.innerHTML = `<div class="empty">Live model unavailable (is the model service up?).</div>`; return; }
  const hist = (m.history || []).slice().reverse();
  el.innerHTML = `<div class="card-head"><div><h3>Live model · v${int(m.version)}</h3>
    <p class="sub">${esc(m.model)} · novelty threshold ${m.novelty_threshold == null ? "–" : m.novelty_threshold.toFixed(2)} ·
    teaching is rolled back if it forgets (old-attack macro-F1 −${pct(m.max_drop, 0)}, any category −${pct(m.max_recall_drop ?? 0.05, 0)})
    or adds false alarms (+${pct(m.max_fpr_rise ?? 0.005, 1)}); it keeps the last epoch that passes</p></div></div>
    ${hist.length ? `<div class="feed" style="max-height:150px">${hist.map((h) => {
      if (h.reset) return `<div class="ev"><span class="tag">reset</span> back to the trained model (v${int(h.version)})</div>`;
      const ok = h.accepted;
      return `<div class="ev"><span class="num muted">v${int(h.version)}</span>
        <span>${ok ? '<span class="tag good">adapted</span>' : '<span class="tag warn">rolled back</span>'}
        ${int(h.labelled_flows)} labelled flows · old-attack F1 ${f3(h.old_attacks_before?.macro_f1)} → ${f3(h.old_attacks_after?.macro_f1)}${
          h.site_holdout ? ` · site false alarms ${pct(h.site_holdout.fpr_before)} → ${pct(h.site_holdout.fpr_after)}` : ""}${
          ok && h.epochs_kept ? ` · ${int(h.epochs_kept)} epoch${h.epochs_kept > 1 ? "s" : ""}` : ""}
        ${ok ? "" : `<span class="muted">(${esc(h.reason || "")})</span>`}</span></div>`;
    }).join("")}</div>` : `<p class="note">No live adaptations yet — the model is exactly as trained.</p>`}`;
}

async function renderDrift() {
  const el = root.querySelector("#st-drift");
  if (!el) return;
  const d = await get("/live/drift").catch(() => null);
  const s = d && d.sites.find((x) => x.site === sel);
  if (!s) { el.innerHTML = "Drift: no new analyst labels for this site yet."; return; }
  const rate = `the model disagreed with your labels on <b>${pct(s.error_rate)}</b> of ${int(s.labelled)} new labels`;
  el.innerHTML = !s.enough_labels ? `Drift: ${rate} (needs ${int(d.min_labels)}+ labels to judge).`
    : s.adapt_recommended ? `<span style="color:var(--warn)"><b>Drift detected:</b> ${rate} — adapting is recommended.</span>`
    : `Drift: ${rate} — below the ${pct(d.threshold, 0)} threshold.`;
}

function renderIncidents(inc) {
  const el = root.querySelector("#st-incidents");
  if (!inc.incidents.length) {
    el.innerHTML = `<div class="empty">No flagged flows in the last 15 minutes${sel ? ` from ${esc(sel)}` : ""}. ${int(inc.n_flows)} flows seen.</div>`;
    return;
  }
  const STATUS_TAG = { open: "warn", reopened: "bad", acknowledged: "", closed: "good" };
  el.innerHTML = inc.incidents.map((i) => {
    const p = i.proposed || {};
    const r = i.record || {};
    const since = r.first_seen ? new Date(r.first_seen).toLocaleTimeString() : "";
    return `<div class="incident" style="border:1px solid var(--grid);border-radius:10px;padding:12px;margin-bottom:10px">
      ${r.id ? `<div class="note" style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
        <b>Incident #${int(r.id)}</b><span class="tag ${STATUS_TAG[r.status] ?? ""}">${esc(r.status)}</span>
        <span>since ${esc(since)}${r.status_by ? ` · ${esc(r.status)} by ${esc(r.status_by)}` : ""}</span>
        <span style="margin-left:auto;display:flex;gap:6px">
          ${r.status !== "acknowledged" ? `<button class="btn small ghost" data-status="acknowledged" data-rec="${int(r.id)}">Acknowledge</button>` : ""}
          ${r.status !== "closed" ? `<button class="btn small ghost" data-status="closed" data-rec="${int(r.id)}">Close</button>`
            : `<button class="btn small ghost" data-status="open" data-rec="${int(r.id)}">Reopen</button>`}
        </span></div>` : ""}
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">
        <div><span class="tag" style="background:${catColor(i.category)};color:#fff">${esc(i.category)}</span>
          <b>${esc(i.key_host)}</b> <span class="muted">(${esc(i.key_role)}, ${int(i.key_host_flows)} flows)</span></div>
        <span class="num muted">${int(i.n_flows)} flows · conf ${pct(i.mean_confidence)}${i.category_uncertain_share >= 0.5
          ? ` · <span style="color:var(--warn)" title="the model is sure this is an attack, less sure which kind">kind uncertain</span>` : ""}</span></div>
      <div class="note" style="margin-top:6px">${int(i.n_sources)} sources → ${int(i.n_destinations)} destinations${i.top_ports?.length ? ` · ports ${i.top_ports.map((x) => esc(x)).join(", ")}` : ""}${i.sites?.length ? ` · ${i.sites.map((x) => esc(x)).join(", ")}` : ""}</div>
      <div class="note" style="margin-top:6px"><b>Proposed (dry run):</b> ${esc(p.action || "investigate")} ${esc(p.target || "")} — ${esc(p.rationale || "")}</div>
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <button class="btn small ghost" data-why="${esc(String((i.flow_ids || [])[0] ?? ""))}" title="Why did the model flag this? (evidence for one of its flows)">Why?</button>
        <button class="btn small" data-label-ids="${esc(JSON.stringify(i.flow_ids || []))}" data-cat="${esc(i.category)}" title="Label these flows for teaching">Confirm as ${esc(i.category)}</button>
        <button class="btn small ghost" data-label-ids="${esc(JSON.stringify(i.flow_ids || []))}" data-cat="Benign">Mark normal (false alarm)</button>
        <span class="muted" style="margin-left:auto">action:</span>
        <button class="btn small" data-decide="approve" data-site="${esc(i.site)}" data-cat="${esc(i.category)}" data-target="${esc(p.target || "")}" title="Record approval — dry run, nothing is executed">Approve (dry run)</button>
        <button class="btn small ghost" data-decide="reject" data-site="${esc(i.site)}" data-cat="${esc(i.category)}" data-target="${esc(p.target || "")}">Reject</button>
      </div><div class="why-box"></div></div>`;
  }).join("");
  el.querySelectorAll("[data-label-ids]").forEach((b) => b.addEventListener("click", () =>
    withBusy(b, () => labelIds(JSON.parse(b.dataset.labelIds), b.dataset.cat))));
  el.querySelectorAll("[data-status]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    try {
      const r = await post(`/live/incident_records/${b.dataset.rec}/status`, { status: b.dataset.status, analyst: "analyst" });
      toast(`incident #${r.id} ${r.status}`); incSig = ""; await tick();
    } catch (e) { toast(e.message); }
  })));
  el.querySelectorAll("[data-why]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const box = b.closest(".incident").querySelector(".why-box");
    if (!b.dataset.why) { box.innerHTML = `<p class="note">No flow to explain.</p>`; return; }
    try {
      const e = await get(`/live/explain/${encodeURIComponent(b.dataset.why)}`);
      const feats = (e.features || []).filter((f) => f.direction === "towards").slice(0, 5)
        .map((f) => `<li>${esc(f.label)}${f.value != null ? ` = <span class="num">${esc(Number(f.value).toPrecision(4))}</span>` : ""}</li>`).join("");
      box.innerHTML = `<div class="callout" style="margin-top:10px">
        <p style="margin:0 0 6px"><b>Why (flow ${int(e.flow_id)}, ${esc(e.src_ip)} → ${esc(e.dst_ip)}):</b> ${esc(e.summary)}</p>
        ${feats ? `<p class="note" style="margin:0">Evidence pushing towards ${esc(e.predicted_label)}:</p><ul class="note" style="margin:4px 0 0 18px">${feats}</ul>` : ""}
        <p class="note" style="margin:6px 0 0">${pct(e.context_share)} of the evidence came from neighbouring flows (${int(e.context_flows)} flows of context) ·
        live model v${int(e.version)}${e.predicted_label !== e.predicted_when_scored ? ` · when scored it said ${esc(e.predicted_when_scored)}; the model has been taught since` : ""}</p></div>`;
    } catch (err) { box.innerHTML = `<p class="note">${esc(err.message)}</p>`; }
  })));
  el.querySelectorAll("[data-decide]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    try {
      const a = await post("/live/actions", { site: b.dataset.site, category: b.dataset.cat, target: b.dataset.target });
      const d = await post(`/actions/${a.id}/decision`, { decision: b.dataset.decide, analyst: "analyst" });
      toast(`${d.status} (dry run): ${d.action} ${d.target} — recorded in the decision log, nothing executed`);
    } catch (e) { toast(e.message); }
  })));
}

function renderUnsure(list) {
  const el = root.querySelector("#st-unsure");
  if (!list.length) { el.innerHTML = `<div class="empty">The model was sure about every recent flow.</div>`; return; }
  el.innerHTML = list.map((u) => {
    const lean = Object.entries(u.leaning || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${esc(k)} ${int(v)}`).join(", ");
    return `<div style="padding:8px 0;border-bottom:1px solid var(--grid)">
      <div style="display:flex;justify-content:space-between"><b>${esc(u.host)}</b><span class="num">${int(u.flows)} flows</span></div>
      <div class="note">${esc(u.site)} · leaning ${lean}</div>
      <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">
        ${CLASSES.map((c) => `<button class="btn small ghost" data-uids="${esc(JSON.stringify(u.flow_ids || []))}" data-cat="${c}">${c === "Benign" ? "Normal" : c}</button>`).join("")}
      </div></div>`;
  }).join("");
  el.querySelectorAll("[data-uids]").forEach((b) => b.addEventListener("click", () =>
    withBusy(b, () => labelIds(JSON.parse(b.dataset.uids), b.dataset.cat))));
}

function renderUnfamiliar(unf) {
  const el = root.querySelector("#st-unfamiliar");
  if (!unf || !unf.length) { el.innerHTML = `<div class="empty">Nothing unfamiliar.</div>`; return; }
  el.innerHTML = unf.map((u) => `<div style="padding:8px 0;border-bottom:1px solid var(--grid)">
    <div style="display:flex;justify-content:space-between"><b>${esc(u.host)}</b><span class="num">${int(u.flows)} flows</span></div>
    <div class="note">${esc(u.site)} · ${int(u.destinations)} destinations${u.ports?.length ? ` · ports ${u.ports.slice(0, 6).map((x) => esc(x)).join(", ")}` : ""}</div>
    <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">
      ${CLASSES.filter((c) => c !== "Benign").map((c) => `<button class="btn small ghost" data-ids="${esc(JSON.stringify(u.flow_ids || []))}" data-cat="${c}">${c}</button>`).join("")}
    </div></div>`).join("");
  el.querySelectorAll("[data-ids]").forEach((b) => b.addEventListener("click", () =>
    withBusy(b, () => labelIds(JSON.parse(b.dataset.ids), b.dataset.cat))));
}

function renderTeach(site) {
  const el = root.querySelector("#st-teach");
  el.innerHTML = `
    <label class="field"><span>If recent traffic${site ? ` from <b>${esc(site)}</b>` : ""} is all normal, say so:</span></label>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px">
      last <input id="st-min" type="number" value="5" min="1" max="240" style="width:64px"> min →
      <button class="btn small" id="st-normal" ${site ? "" : "disabled title='pick a site first'"}>Mark normal</button>
    </div>
    <div id="st-drift" class="note" style="margin-bottom:10px"></div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="btn primary" id="st-adapt">Adapt model now</button>
      <span class="note">learns from every label not yet used</span>
    </div>
    <p id="st-adapt-out" class="note" style="margin-top:8px"></p>`;
  const normal = el.querySelector("#st-normal");
  if (normal) normal.addEventListener("click", () => withBusy(normal, async () => {
    try {
      const r = await post("/live/label", { label: "Benign", site, last_minutes: Number(el.querySelector("#st-min").value) });
      toast(`labelled ${r.labelled} flows normal` + (r.skipped_suspicious ? ` · skipped ${r.skipped_suspicious} flagged/unfamiliar flows (label those individually)` : ""));
    } catch (e) { toast(e.message); }
  }));
  el.querySelector("#st-adapt").addEventListener("click", (e) => withBusy(e.target, async () => {
    const out = el.querySelector("#st-adapt-out");
    try {
      const r = await post("/live/adapt", site ? { site } : {});
      out.innerHTML = r.accepted
        ? `<span style="color:var(--good)">Adapted to v${int(r.version)} from ${int(r.labelled_flows)} labels (${int(r.epochs_kept)} epoch${r.epochs_kept > 1 ? "s" : ""}). Old-attack macro-F1 ${f3(r.old_attacks_before.macro_f1)} → ${f3(r.old_attacks_after.macro_f1)}${
            r.site_holdout ? `; this site's false alarms ${pct(r.site_holdout.fpr_before)} → ${pct(r.site_holdout.fpr_after)}` : ""}.</span>`
        : `<span style="color:var(--warn)">Rolled back: ${esc(r.reason || "would forget old attacks")}.</span>`;
      await tick();
    } catch (err) { out.textContent = err.message; }
  }));
}

async function labelIds(ids, category) {
  if (!ids || !ids.length) { toast("no flows to label"); return; }
  try { const r = await post("/live/label", { label: category, flow_ids: ids }); toast(`labelled ${r.labelled} flows as ${category}`); }
  catch (e) { toast(e.message); }
}

const f3 = (v) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(3));
