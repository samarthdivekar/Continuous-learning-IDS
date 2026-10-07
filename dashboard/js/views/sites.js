// Live sites: real traffic from sensor machines (src/live). Each sensor uploads short capture chunks;
// the server converts them with the pinned CICFlowMeter, scores them with the live model and files them
// per site. Here you watch per-site traffic, triage incidents (dry-run rules), label flows and adapt the
// model without forgetting. Distinct from "Live stream", which replays the recorded dataset.
import { catColor, css, esc, get, int, pct, post, toast } from "../lib/core.js";
import { GraphView } from "../lib/graphview.js";
import { withBusy } from "../lib/ui.js";

let root, timer, sel = null, teachSel, incSig = "", gview, gWindow = null;

const CLASSES = ["Benign", "BruteForce", "DoS", "WebAttack", "Infiltration", "Botnet", "PortScan", "DDoS"];

export async function mount(el) {
  root = el;
  root.innerHTML = `
    <div class="view-head"><div><h2>Live sites</h2>
      <p>Real traffic from sensor machines, not the recorded dataset. Each sensor (<span class="mono">sensor/agent.py</span>)
      sends short capture chunks; the server runs the same CICFlowMeter the training data came from, scores every flow
      with the live model, and shows it per site. Nothing is ever blocked — proposed actions are a dry run.</p></div>
      <div class="toolbar">
        <button class="btn" id="st-reset" title="Forget live learning and go back to the trained model">⟲ Reset model</button>
      </div></div>
    <div class="card" id="st-nosites" style="margin-bottom:16px"><div class="empty">
      No sensors have reported yet. On a machine to monitor, run:<br>
      <span class="mono">python sensor/agent.py --server http://THIS-PC:8000 --site home-lan --iface &lt;n&gt;</span><br>
      or replay a capture: <span class="mono">python sensor/agent.py --server http://THIS-PC:8000 --site lab --replay attack.pcap</span>
    </div></div>
    <div id="st-sites" class="grid g4" style="margin-bottom:16px"></div>
    <div class="card" id="st-graphcard" style="margin-bottom:16px">
      <div class="card-head"><div><h3 id="st-gtitle">Live traffic graph</h3>
        <p class="sub" id="st-gsub">hosts are dots, flows are lines; red = the model predicts an attack. Scroll to zoom, drag to pan, hover a host.</p></div>
        <div class="toolbar"><button class="icon-btn small" id="st-gfit" title="Fit the graph">⤢ Fit</button></div></div>
      <div class="graph-stage" id="st-gstage" style="height:340px"></div>
      <div class="legend" id="st-glegend" style="margin-top:10px"></div></div>
    <div class="card" id="st-model" style="margin-bottom:16px"></div>
    <div class="grid g-8-4">
      <div class="card"><div class="card-head"><div><h3>Incidents <span id="st-scope" class="muted"></span></h3>
        <p class="sub">flagged flows of recent chunks, grouped by attacker/victim; each carries a dry-run rule</p></div></div>
        <div id="st-incidents"></div></div>
      <div class="grid" style="gap:16px">
        <div class="card"><h3>Unfamiliar traffic</h3><p class="sub">called benign but unlike anything seen in training — candidates for a new attack</p>
          <div id="st-unfamiliar"></div></div>
        <div class="card"><h3>Teach the model</h3>
          <p class="sub">label recent traffic, then adapt. Adaptation is gated: if it would forget old attacks, it is rolled back.</p>
          <div id="st-teach"></div></div>
      </div>
    </div>`;
  root.querySelector("#st-reset").addEventListener("click", (e) =>
    withBusy(e.target, async () => { try { const r = await post("/live/reset"); toast(`model reset to v${r.version}`); await tick(); } catch (err) { toast(err.message); } }));
  gview = new GraphView(root.querySelector("#st-gstage"));
  root.querySelector("#st-gfit").addEventListener("click", () => gview.fit());
  await tick();
  timer = setInterval(tick, 3000);
}

export function refresh() { tick(); }
export function activate() { tick(); }

async function tick() {
  if (!root || !root.isConnected) { clearInterval(timer); return; }
  let sites;
  try { sites = (await get("/live/sites")).sites; } catch { return; }
  root.querySelector("#st-nosites").style.display = sites.length ? "none" : "";
  renderSites(sites);
  if (sel && !sites.some((s) => s.site === sel)) sel = null;
  if (!sel && sites.length) sel = sites[0].site;
  root.querySelector("#st-scope").textContent = sel ? `· ${sel}` : "· all sites";

  const badge = document.querySelector("#sites-badge");
  if (badge) badge.classList.toggle("hidden", !sites.some((s) => s.online && s.flows_5min));

  await renderModel();
  const q = sel ? `site=${encodeURIComponent(sel)}&windows=40` : "windows=40";
  const inc = await get(`/live/incidents?${q}`).catch(() => null);
  if (inc) {
    // re-render the incident list only when it actually changed, so clicks/scroll are not interrupted
    const sig = JSON.stringify([sel, inc.n_flows, inc.incidents.map((i) => [i.category, i.key_host, i.n_flows]),
      inc.unfamiliar.map((u) => [u.host, u.flows])]);
    if (sig !== incSig) { incSig = sig; renderIncidents(inc); renderUnfamiliar(inc.unfamiliar); }
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
  const g = await get(`/live/graph/${latest.window_id}`).catch(() => null);
  if (!g || gWindow !== latest.window_id) return;
  gview.mode = "truth";
  gview.setData(g);
  root.querySelector("#st-gtitle").textContent = `Live traffic graph · ${esc(latest.site)}`;
  root.querySelector("#st-gsub").innerHTML = `${int(g.n_nodes)} hosts, ${int(g.n_edges)} flows · ${int(g.n_attack_edges)} predicted attack` +
    (g.truncated ? ` · showing the busiest ${g.nodes.length} hosts` : "");
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
      <div class="note">flagged / 5 min · ${int(s.flows_5min)} flows · ${s.online ? "online" : `${int(s.seconds_since)}s ago`}${s.unfamiliar_5min ? ` · <span style="color:var(--warn)">${int(s.unfamiliar_5min)} unfamiliar</span>` : ""}</div>
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
    rolls back if old-attack macro-F1 drops &gt; ${pct(m.max_drop)}</p></div></div>
    ${hist.length ? `<div class="feed" style="max-height:150px">${hist.map((h) => {
      if (h.reset) return `<div class="ev"><span class="tag">reset</span> back to the trained model (v${int(h.version)})</div>`;
      const ok = h.accepted;
      return `<div class="ev"><span class="num muted">v${int(h.version)}</span>
        <span>${ok ? '<span class="tag good">adapted</span>' : '<span class="tag warn">rolled back</span>'}
        ${int(h.labelled_flows)} labelled flows · old-attack F1 ${f3(h.old_attacks_before?.macro_f1)} → ${f3(h.old_attacks_after?.macro_f1)}
        ${ok ? "" : `<span class="muted">(${esc(h.reason || "")})</span>`}</span></div>`;
    }).join("")}</div>` : `<p class="note">No live adaptations yet — the model is exactly as trained.</p>`}`;
}

function renderIncidents(inc) {
  const el = root.querySelector("#st-incidents");
  if (!inc.incidents.length) {
    el.innerHTML = `<div class="empty">No flagged flows in the last 40 chunks${sel ? ` from ${esc(sel)}` : ""}. ${int(inc.n_flows)} flows seen.</div>`;
    return;
  }
  el.innerHTML = inc.incidents.map((i) => {
    const p = i.proposed || {};
    return `<div class="incident" style="border:1px solid var(--grid);border-radius:10px;padding:12px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">
        <div><span class="tag" style="background:${catColor(i.category)};color:#fff">${esc(i.category)}</span>
          <b>${esc(i.key_host)}</b> <span class="muted">(${esc(i.key_role)}, ${int(i.key_host_flows)} flows)</span></div>
        <span class="num muted">${int(i.n_flows)} flows · conf ${pct(i.mean_confidence)}</span></div>
      <div class="note" style="margin-top:6px">${int(i.n_sources)} sources → ${int(i.n_destinations)} destinations${i.top_ports?.length ? ` · ports ${i.top_ports.map((x) => esc(x)).join(", ")}` : ""}${i.sites?.length ? ` · ${i.sites.map((x) => esc(x)).join(", ")}` : ""}</div>
      <div class="note" style="margin-top:6px"><b>Proposed (dry run):</b> ${esc(p.action || "investigate")} ${esc(p.target || "")} — ${esc(p.rationale || "")}</div>
      <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn small" data-label-ids="${esc(JSON.stringify(i.flow_ids || []))}" data-cat="${esc(i.category)}">Confirm as ${esc(i.category)}</button>
        <button class="btn small ghost" data-label-ids="${esc(JSON.stringify(i.flow_ids || []))}" data-cat="Benign">Mark normal (false alarm)</button>
      </div></div>`;
  }).join("");
  el.querySelectorAll("[data-label-ids]").forEach((b) => b.addEventListener("click", () =>
    withBusy(b, () => labelIds(JSON.parse(b.dataset.labelIds), b.dataset.cat))));
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
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button class="btn primary" id="st-adapt">Adapt model now</button>
      <span class="note">learns from every label not yet used</span>
    </div>
    <p id="st-adapt-out" class="note" style="margin-top:8px"></p>`;
  const normal = el.querySelector("#st-normal");
  if (normal) normal.addEventListener("click", () => withBusy(normal, async () => {
    try {
      const r = await post("/live/label", { label: "Benign", site, last_minutes: Number(el.querySelector("#st-min").value) });
      toast(`labelled ${r.labelled} flows normal`);
    } catch (e) { toast(e.message); }
  }));
  el.querySelector("#st-adapt").addEventListener("click", (e) => withBusy(e.target, async () => {
    const out = el.querySelector("#st-adapt-out");
    try {
      const r = await post("/live/adapt", site ? { site } : {});
      out.innerHTML = r.accepted
        ? `<span style="color:var(--good)">Adapted to v${int(r.version)} from ${int(r.labelled_flows)} labels. Old-attack macro-F1 ${f3(r.old_attacks_before.macro_f1)} → ${f3(r.old_attacks_after.macro_f1)} (kept).</span>`
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
