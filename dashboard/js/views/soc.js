// Incident queue — the analyst's working screen.
//
// Three panes: what to look at (scope and filters), what is waiting (the ranked queue),
// and the one under review (evidence, then the proposed containment). The queue is
// keyboard-first: j/k to move, Enter to open, a/r to decide, c to copy the rule.
//
// Nothing here executes anything. Approving records a decision and says DRY RUN at every
// step, including in the confirmation.
import { $, $$, catColor, downloadCsv, esc, get, int, label, openApi, pct, post, prefs, table, toast } from "../lib/core.js";
import { mount } from "../lib/charts.js";
import { confirmDialog, makeSortable, showError, skeleton, withBusy } from "../lib/ui.js";

let root, catalog = [], current = null, selected = null;

// readable feature values: 56737 -> "56,737", never "5.674e+4"
const fmtValue = (v) => (v == null ? "–"
  : Math.abs(v - Math.round(v)) < 1e-9 ? Math.round(v).toLocaleString()
  : Math.abs(v) >= 1e-4 ? Number(v.toPrecision(4)).toLocaleString() : v.toExponential(2));
const NEURAL = ["gnn_ewc_replay", "ffnn_ewc_replay", "gnn_naive"];
const STATUS_TAG = { open: "warn", reopened: "bad", acknowledged: "", closed: "good" };
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
      <p>Where every incident is triaged. Thousands of flagged flows become a handful of <b>incidents</b>, one per
      attacker/victim cluster. Open one to see <b>why</b> it was flagged and the <b>containment we would propose</b>; you
      approve or reject, and nothing is ever executed. <b>Live traffic</b> shows incidents from the sites on
      <a href="#sites">Live sites</a> (sensors, the cyber range, the sandbox). <b>Recorded test data</b> is a practice queue
      on the dataset's held-out windows, where every incident can be checked against ground truth.</p></div>
      <span class="tag" id="soc-svc"></span></div>

    <div class="grid g4" id="soc-kpis"></div>

    <div class="triage" style="margin-top:16px">
      <div class="card" id="soc-controls">
        <h3>Source</h3>
        <div class="seg" id="soc-source" role="group" aria-label="incident source" style="width:100%;margin-bottom:14px">
          <button data-v="live" title="Incidents from real traffic: sensors, the cyber range and the sandbox replay" style="flex:1">Live</button>
          <button data-v="recorded" title="The dataset's held-out test windows, with ground truth" style="flex:1">Recorded</button>
        </div>
        <div id="soc-live-ctl">
          <label class="stacked">Site
            <select id="soc-site"><option value="">All sites</option></select></label>
          <label class="stacked">Time span
            <select id="soc-minutes"><option value="15">last 15 minutes</option><option value="60" selected>last hour</option>
              <option value="1440">last 24 hours</option></select></label>
        </div>
        <div id="soc-rec-ctl" class="hidden">
        <h3>What to review</h3>
        <div class="seg" id="soc-scope" role="group" aria-label="scope" style="width:100%;margin-bottom:12px">
          <button data-v="scan" class="on" title="Incidents across the most recent windows, like a shift's queue" style="flex:1">Recent</button>
          <button data-v="window" title="Incidents in one traffic window" style="flex:1">One window</button>
        </div>
        <label class="stacked hidden" id="soc-win-wrap">Traffic window
          <select id="soc-win"></select></label>
        <label class="stacked" id="soc-scan-wrap">Windows to scan
          <select id="soc-limit"><option>10</option><option selected>20</option><option>50</option></select></label>
        <label class="stacked">Detector
          <select id="soc-model">${NEURAL.map((m) => `<option value="${m}">${esc(label(m))}</option>`).join("")}</select></label>
        </div>
        <label class="stacked" title="Hide alerts the model is less sure about than this">
          Minimum confidence <span id="soc-th-v" class="num muted">0%</span>
          <input type="range" id="soc-th" min="0" max="0.99" step="0.01" value="0" style="width:100%"></label>
        <button class="btn primary" id="soc-go" style="width:100%;margin-top:4px">Refresh</button>

        <h3 style="margin-top:18px">Filter the queue</h3>
        <label class="stacked">Category
          <select id="soc-cat" aria-label="filter by attack category"><option value="">All categories</option></select></label>
        <label class="stacked">Severity
          <select id="soc-sev" aria-label="filter by severity">
            <option value="">Any severity</option><option value="6">Critical only</option><option value="3">High and above</option>
          </select></label>

        <h3 style="margin-top:18px">Export</h3>
        <div class="toolbar">
          <button class="icon-btn small" id="soc-csv" aria-label="Download these incidents as CSV" title="Download the incidents you can see, as CSV">⤓ CSV</button>
          <button class="icon-btn small" id="soc-cef" aria-label="Download for a SIEM in CEF format" title="Download for a SIEM (ArcSight CEF)">⤓ CEF</button>
        </div>
        <p class="note" data-secondary>Keyboard: <span class="kbd">j</span>/<span class="kbd">k</span> move,
          <span class="kbd">Enter</span> open, <span class="kbd">a</span> approve, <span class="kbd">r</span> reject,
          <span class="kbd">c</span> copy rule.</p>
      </div>

      <div class="card">
        <div class="card-head"><div><h3>Queue <span class="tag" id="soc-count">—</span></h3>
          <p class="sub">most severe first · severity = size × confidence</p></div></div>
        <div id="soc-list" class="window-list" role="listbox" aria-label="incidents" tabindex="0" style="max-height:680px">
          <div class="empty"><span class="title">Nothing loaded yet</span>Choose a source on the left.</div>
        </div>
      </div>

      <div class="card" id="soc-detail">
        <div class="empty"><span class="title">No incident selected</span>Pick one from the queue, or press <span class="kbd">j</span>.</div>
      </div>
    </div>

    <div class="card" style="margin-top:16px"><div class="card-head"><div><h3>Decision log</h3>
      <p class="sub">every proposed action and the analyst's decision · dry run only, nothing was executed</p></div>
      <div class="seg" id="soc-filter" role="group" aria-label="decision log filter"><button data-v="" class="on">All</button><button data-v="proposed">Pending</button>
        <button data-v="approved">Approved</button><button data-v="rejected">Rejected</button></div></div>
      <div id="soc-log"></div></div>`;

  try { catalog = (await get("/windows/catalog")).filter((w) => w.split === "test" && w.n_attack > 0); }
  catch (e) { catalog = []; showError($("#soc-list", root), e, { what: "the window catalogue" }); }
  catalog.sort((a, b) => b.n_attack - a.n_attack);
  $("#soc-win", root).innerHTML = catalog.length ? catalog.map((w) =>
    `<option value="${w.window_id}">#${w.window_id} · ${esc(w.top_attack || w.task_category)} · ${int(w.n_attack)} attack flows</option>`).join("")
    : `<option value="">no test windows with attacks</option>`;

  const th = $("#soc-th", root);
  th.addEventListener("input", () => { $("#soc-th-v", root).textContent = `${Math.round(th.value * 100)}%`; });
  $$("#soc-scope button", root).forEach((b) => b.addEventListener("click", () => {
    $$("#soc-scope button", root).forEach((x) => x.classList.toggle("on", x === b));
    const scan = b.dataset.v === "scan";
    $("#soc-win-wrap", root).classList.toggle("hidden", scan);
    $("#soc-scan-wrap", root).classList.toggle("hidden", !scan);
    $("#soc-go", root).textContent = scan ? "Scan windows" : "Load incidents";
  }));
  $$("#soc-source button", root).forEach((b) => b.addEventListener("click", () => setSource(b.dataset.v, true)));
  $$("#soc-site, #soc-minutes", root).forEach((el) => el.addEventListener("change", () => withBusy($("#soc-go", root), load)));
  $("#soc-go", root).addEventListener("click", () => withBusy($("#soc-go", root), load));
  $$("#soc-filter button", root).forEach((b) => b.addEventListener("click", () => {
    $$("#soc-filter button", root).forEach((x) => x.classList.toggle("on", x === b)); log(b.dataset.v);
  }));
  $$("#soc-cat, #soc-sev", root).forEach((el) => el.addEventListener("change", renderList));
  $("#soc-csv", root).addEventListener("click", () => {
    const rows = visibleIncidents().map(({ proposed, sample_edges, ...keep }) => ({
      ...keep, action: proposed?.action, target: proposed?.target, rationale: proposed?.rationale }));
    downloadCsv(`incidents_window${current?.window_id ?? "scan"}.csv`, rows);
  });
  $("#soc-cef", root).addEventListener("click", () => {
    if (!current) { toast("load a window first"); return; }
    if (current.live) {
      const site = $("#soc-site", root).value;
      openApi(`/live/incidents/cef?minutes=${$("#soc-minutes", root).value}${site ? `&site=${encodeURIComponent(site)}` : ""}`,
              { filename: `live_incidents_${site || "all"}.cef` });
      return;
    }
    if (current.window_id == null) { toast("CEF export covers one window — switch to One window"); return; }
    openApi(`/incidents/${current.window_id}/cef?model=${current.model}&threshold=${current.threshold || 0}`,
            { filename: `incidents_w${current.window_id}.cef` });
  });
  $("#soc-model", root).value = prefs.get("soc.model", "gnn_ewc_replay");
  window.addEventListener("keydown", onKey);
  log("");
  // Live traffic by default once any site has reported in the last hour; otherwise the practice queue.
  let sites = [];
  try { sites = (await get("/live/sites")).sites || []; } catch { /* model service down: recorded still works */ }
  $("#soc-site", root).innerHTML = `<option value="">All sites</option>` + sites.map((s) => `<option>${esc(s.site)}</option>`).join("");
  const recent = sites.some((s) => s.seconds_since < 3600);
  await setSource(pendingOpen() ? "live" : prefs.get("soc.source", recent ? "live" : "recorded"), false);
  liveTimer = setInterval(() => {                    // keep the live queue current without losing the selection
    if (current?.live && root?.closest(".view")?.classList.contains("on")) load(true);
  }, 10000);
}
export { mount_ as mount };
export const activate = () => {
  log(currentFilter());
  if (pendingOpen()) setSource("live", false);
};
export const refresh = () => { if (current) renderList(); };

let liveTimer = null;
// Live sites hands an incident over with "Triage →": the record id waits in sessionStorage until this page opens it
const pendingOpen = () => { try { return sessionStorage.getItem("gnnids.openIncident"); } catch { return null; } };

async function setSource(src, remember) {
  if (remember) prefs.set("soc.source", src);
  $$("#soc-source button", root).forEach((x) => x.classList.toggle("on", x.dataset.v === src));
  const live = src === "live";
  $("#soc-live-ctl", root).classList.toggle("hidden", !live);
  $("#soc-rec-ctl", root).classList.toggle("hidden", live);
  const scan = $("#soc-scope button.on", root)?.dataset.v === "scan";
  $("#soc-go", root).textContent = live ? "Refresh" : scan ? "Scan windows" : "Load incidents";
  $("#soc-svc", root).textContent = live ? "live traffic · live model" : "recorded test windows · ground truth available";
  await withBusy($("#soc-go", root), () => load());
}

/** Called by the command palette ("open incident 7"). True when the incident exists here. */
export function openIncident(id) {
  const match = current?.incidents?.find((i) => numberOf(i) === id);
  if (!match) return false;
  pick(uidOf(match));
  $("#soc-detail", root)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return true;
}

const currentFilter = () => $("#soc-filter button.on", root)?.dataset.v || "";
// a scan mixes windows, so each incident carries its own window id
const windowOf = (i) => i?.window_id ?? current?.window_id;
// live incidents are stored records with a stable id; recorded ones are ranks within a window
const uidOf = (i) => (i.record ? `live-${i.record.id}` : `${windowOf(i)}-${i.incident_id}`);
const numberOf = (i) => (i.record ? i.record.id : i.rank ?? i.incident_id);
const selectedIncident = () => current?.incidents?.find((x) => uidOf(x) === selected);

/* ------------------------------------------------------------------ keyboard triage */
function onKey(e) {
  const active = root?.closest(".view")?.classList.contains("on");
  if (!active || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
  if (document.querySelector(".dialog, .palette")) return;        // a dialog owns the keyboard
  const shown = visibleIncidents();
  if (!shown.length) return;
  const at = shown.findIndex((i) => uidOf(i) === selected);
  const key = e.key.toLowerCase();
  if (key === "j" || key === "k") {
    e.preventDefault();
    const next = key === "j" ? Math.min(shown.length - 1, at + 1) : Math.max(0, at - 1);
    pick(uidOf(shown[next < 0 ? 0 : next]));
    $(`#soc-list button[data-id="${CSS.escape(selected)}"]`, root)?.scrollIntoView({ block: "nearest" });
  } else if (key === "enter" && selected) {
    e.preventDefault();
    $("#soc-detail", root)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } else if (key === "a" || key === "r") {
    const i = selectedIncident();
    if (!i) return;
    e.preventDefault();
    decide(i, key === "a" ? "approve" : "reject");
  } else if (key === "c") {
    e.preventDefault();
    copyRule();
  }
}

/* ------------------------------------------------------------------ loading */
async function load(quiet = false) {
  const live = $("#soc-source button.on", root)?.dataset.v === "live";
  const scan = $("#soc-scope button.on", root).dataset.v === "scan";
  const wid = $("#soc-win", root).value, model = $("#soc-model", root).value, th = $("#soc-th", root).value;
  if (!live && !scan && !wid) return;
  if (!live) prefs.set("soc.model", model);
  if (!quiet) {
    $("#soc-list", root).innerHTML = skeleton("table");
    $("#soc-detail", root).innerHTML = skeleton("lines", 2);
  }
  let next;
  try {
    if (live) {
      const site = $("#soc-site", root).value;
      next = await get(`/live/incidents?windows=500&minutes=${$("#soc-minutes", root).value}&min_confidence=${th}`
                       + (site ? `&site=${encodeURIComponent(site)}` : ""));
      next.live = true;
      next.model = "live model";
      next.threshold = Number(th);
    } else {
      next = scan
        ? await get(`/incidents/scan?limit=${$("#soc-limit", root).value}&model=${model}&threshold=${th}`)
        : await get(`/incidents/${wid}?model=${model}&threshold=${th}`);
    }
  } catch (e) {
    if (quiet) return;
    showError($("#soc-list", root), e, { what: "the incident queue" });
    $("#soc-detail", root).innerHTML = `<div class="empty"><span class="title">No incident selected</span></div>`;
    return;
  }
  // a quiet refresh keeps the incident under review open if it is still in the queue
  const keep = quiet && selected && next.incidents.some((i) => uidOf(i) === selected) ? selected : null;
  current = next;
  renderKpis(); renderList();
  const want = pendingOpen();
  if (want && current.live) {
    try { sessionStorage.removeItem("gnnids.openIncident"); } catch { /* ignore */ }
    const hit = current.incidents.find((i) => String(i.record?.id) === want);
    if (hit) { pick(uidOf(hit)); return; }
    toast(`incident #${want} is not in this time span`);
  }
  if (keep) { selected = keep; renderList(); return; }
  selected = null;
  if (current.incidents.length) pick(uidOf(current.incidents[0]));
  else $("#soc-detail", root).innerHTML = `<div class="empty"><span class="title">No incident</span>${
    current.live ? "No site raised a confident alarm in this time span. Send traffic from Live sites (the sandbox replay is quickest)." : ""}</div>`;
}

function kpi(title, value, detail) {
  return `<div class="card kpi"><div class="label">${esc(title)}</div><div class="value num">${value}</div><div class="detail">${detail}</div></div>`;
}

function renderKpis() {
  const c = current, m = c.metrics || {};
  if (c.live) {
    const unsure = (c.unsure || []).reduce((s, u) => s + u.flows, 0);
    const open = c.incidents.filter((i) => ["open", "reopened"].includes(i.record?.status)).length;
    $("#soc-kpis", root).innerHTML = [
      kpi("Flows seen", int(c.n_flows), `live traffic, last ${c.minutes >= 60 ? `${c.minutes / 60} h` : `${c.minutes} min`}`),
      kpi("Confident alarms", int(c.flagged_flows), `${pct(c.flagged_flows / Math.max(1, c.n_flows))} of the traffic`),
      kpi("Incidents", int(c.incidents.length), `${int(open)} open or reopened`),
      kpi("Unsure (no alarm)", int(unsure), unsure ? `flows sent to an analyst on <a href="#sites">Live sites</a>` : "the model was sure about every flow"),
    ].join("");
    return;
  }
  const scan = c.windows_scanned != null;
  const ratio = c.incidents.length ? c.flagged_flows / c.incidents.length : 0;
  $("#soc-kpis", root).innerHTML = [
    kpi(scan ? "Flows scanned" : "Flows in window", int(c.n_flows),
        scan ? `${int(c.windows_scanned)} windows analysed` : "network conversations analysed"),
    kpi("Flagged flows", int(c.flagged_flows),
        `${pct(c.flagged_flows / Math.max(1, c.n_flows))} of ${scan ? "the scanned traffic" : "the window"}`),
    kpi("Incidents", int(c.incidents.length), c.incidents.length ? `≈ ${int(Math.round(ratio))} alerts folded into each` : "nothing to review"),
    scan
      ? kpi("Busiest window", c.per_window?.length
            ? `#${[...c.per_window].sort((a, b) => b.incidents - a.incidents)[0].window_id}` : "–",
            "most incidents in this scan")
      : kpi("Incidents that are real", m.incident_precision == null ? "–" : pct(m.incident_precision, 0),
            `${int(m.true_incidents)} of ${int(m.incidents)} · checked against ground truth (demo only)`),
  ].join("");
}

function sevTag(i) {
  const s = i.severity;
  return s >= 6 ? `<span class="tag bad">critical</span>` : s >= 3 ? `<span class="tag warn">high</span>` : `<span class="tag">low</span>`;
}

/** Incidents after the category / severity filters. */
function visibleIncidents() {
  if (!current) return [];
  const cat = $("#soc-cat", root)?.value || "";
  const minSev = Number($("#soc-sev", root)?.value || 0);
  return current.incidents.filter((i) => (!cat || i.category === cat) && i.severity >= minSev);
}

function renderList() {
  const list = $("#soc-list", root);
  const count = $("#soc-count", root);
  if (!current.incidents.length) {
    count.textContent = "0";
    list.innerHTML = current.live
      ? `<div class="empty"><span class="title">No live incidents</span>No confident alarm in this time span. Get traffic in on <a href="#sites">Live sites</a>.</div>`
      : `<div class="empty"><span class="title">Nothing flagged</span>No flow passed the confidence threshold in this window.</div>`;
    return;
  }
  const cats = [...new Set(current.incidents.map((i) => i.category))].sort();
  const catSel = $("#soc-cat", root);
  const keep = catSel.value;
  catSel.innerHTML = `<option value="">All categories</option>` + cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  catSel.value = cats.includes(keep) ? keep : "";

  const shown = visibleIncidents();
  count.textContent = shown.length === current.incidents.length
    ? `${shown.length}` : `${shown.length} of ${current.incidents.length}`;
  if (!shown.length) {
    list.innerHTML = `<div class="empty"><span class="title">Filtered out</span>No incident matches these filters.</div>`;
    return;
  }
  const maxSev = Math.max(...shown.map((i) => i.severity));
  list.innerHTML = shown.map((i) => `
    <button data-id="${esc(uidOf(i))}" role="option" aria-selected="${selected === uidOf(i)}"
            class="${selected === uidOf(i) ? "on" : ""}" style="grid-template-columns:44px 1fr auto">
      <span class="num muted">#${numberOf(i)}</span>
      <span><span class="swatch" style="background:${catColor(i.category)}"></span><b>${esc(i.category)}</b>
        · ${i.key_role === "source" ? "from" : "against"} <span class="mono">${esc(i.key_host)}</span>
        ${i.record ? ` <span class="tag ${STATUS_TAG[i.record.status] ?? ""}">${esc(i.record.status)}</span> <span class="tag">${esc(i.site)}</span>` : ""}
        <div class="muted" style="font-size:13px">${int(i.n_flows)} flows · ${int(i.n_sources)} source(s) → ${int(i.n_destinations)} destination(s) · ${pct(i.mean_confidence, 0)} confident
          ${i.true_attack_share != null ? (i.true_attack_share > 0.5 ? ` · <span style="color:var(--good)">real attack</span>` : ` · <span style="color:var(--critical)">false alarm</span>`) : ""}</div>
        <div class="bar-mini"><i style="width:${(100 * i.severity / maxSev).toFixed(1)}%"></i></div></span>
      <span>${sevTag(i)}</span>
    </button>`).join("");
  $$("#soc-list button", root).forEach((b) => b.addEventListener("click", () => pick(b.dataset.id)));
}

/* ------------------------------------------------------------------ detail pane */
async function pick(uid) {
  selected = uid;
  $$("#soc-list button", root).forEach((b) => {
    const on = b.dataset.id === uid;
    b.classList.toggle("on", on);
    b.setAttribute("aria-selected", String(on));
  });
  const i = selectedIncident();
  if (!i) return;
  const p = i.proposed || {};
  const det = $("#soc-detail", root);
  det.innerHTML = `
    <div class="card-head"><div>
      <h3>Incident #${numberOf(i)} · ${esc(i.category)} ${sevTag(i)}
        ${i.window_id != null ? `<span class="tag">window ${i.window_id}</span>` : ""}
        ${i.record ? `<span class="tag">${esc(i.site)}</span> <span class="tag ${STATUS_TAG[i.record.status] ?? ""}">${esc(i.record.status)}</span>` : ""}</h3>
      <p class="sub">${i.record ? `first seen ${esc(localTime(i.record.first_seen))} · last active ${esc(localTime(i.record.last_seen))} · `
        : i.start ? `${esc(i.start.replace("T", " ").slice(0, 19))} → ${esc(i.end.replace("T", " ").slice(11, 19))} · ` : ""}key host <span class="mono">${esc(i.key_host)}</span> (${esc(i.key_role)}, ${int(i.key_host_flows)} flows)</p>
    </div>
    ${i.record ? `<div class="toolbar">
      ${i.record.status !== "acknowledged" ? `<button class="btn small" id="soc-ack">Acknowledge</button>` : ""}
      ${i.record.status !== "closed" ? `<button class="btn small" id="soc-close">Close</button>` : `<button class="btn small" id="soc-reopen">Reopen</button>`}
    </div>` : ""}</div>

    <h4 class="section">Why was this flagged?</h4>
    <div id="soc-why">${skeleton("lines")}</div>

    <h4 class="section">Proposed containment <span class="tag dry">dry run</span></h4>
    <div class="callout"><b>${esc(ACTION_TEXT[p.action] || p.action || "—")}</b> — <span class="mono">${esc(p.target || "—")}</span><br>${esc(p.rationale || "")}</div>
    ${p.rules && (p.rules.linux || p.rules.windows) ? `
      <div class="seg" id="soc-rule-seg" role="group" aria-label="rule format" style="margin-top:10px">
        <button data-v="linux" class="on">Linux (iptables)</button><button data-v="windows">Windows Firewall</button></div>
      <pre class="rule mono" id="soc-rule">${esc(p.rules.linux || "")}</pre>` : ""}
    <div class="toolbar" style="margin-top:10px">
      <button class="btn" id="soc-copy" title="Copy the rule shown above (c)">Copy rule</button>
      ${i.record ? "" : `<button class="btn" id="soc-report" title="Open a printable report (Print → Save as PDF)">Open report</button>`}
    </div>

    <h4 class="section">Decision</h4>
    <div class="toolbar">
      <input type="text" id="soc-analyst" placeholder="your name" aria-label="analyst name"
             value="${esc(prefs.get("analyst", ""))}" style="width:150px" maxlength="64">
      <input type="text" id="soc-note" placeholder="note (optional)" aria-label="note"
             style="flex:1;min-width:140px" maxlength="1000">
    </div>
    <div class="toolbar" style="margin-top:8px" id="soc-decide">
      <button class="btn primary" id="soc-approve">Approve <span class="kbd">a</span></button>
      <button class="btn danger" id="soc-reject">Reject <span class="kbd">r</span></button>
    </div>
    <p class="note">Approving records the decision only. Connecting approved rules to a real firewall is a deployment
      choice deliberately left out of this project.</p>`;

  $$("#soc-rule-seg button", det).forEach((b) => b.addEventListener("click", () => {
    $$("#soc-rule-seg button", det).forEach((x) => x.classList.toggle("on", x === b));
    $("#soc-rule", det).textContent = p.rules[b.dataset.v] || "";
  }));
  $("#soc-copy", det).addEventListener("click", copyRule);
  $("#soc-report", det)?.addEventListener("click", () => openApi(
    `/incidents/${windowOf(i)}/report?incident_id=${i.incident_id}&model=${current.model}`
    + `&threshold=${current.threshold || 0}`));
  for (const [id, status] of [["#soc-ack", "acknowledged"], ["#soc-close", "closed"], ["#soc-reopen", "open"]]) {
    $(id, det)?.addEventListener("click", (e) => withBusy(e.target, async () => {
      try {
        const analyst = $("#soc-analyst", root)?.value.trim() || prefs.get("analyst", "") || "analyst";
        const r = await post(`/live/incident_records/${i.record.id}/status`, { status, analyst });
        toast(`incident #${r.id} ${r.status}`);
        await load(true); pick(uidOf(i));
      } catch (err) { toast(err.message); }
    }));
  }
  $("#soc-approve", det).addEventListener("click", () => decide(i, "approve"));
  $("#soc-reject", det).addEventListener("click", () => decide(i, "reject"));
  explain(i);
}

async function copyRule() {
  const rule = $("#soc-rule", root)?.textContent || "";
  if (!rule) { toast("no rule for this incident"); return; }
  try { await navigator.clipboard.writeText(rule); toast("rule copied to the clipboard"); }
  catch { toast("could not copy — select the text manually"); }
}

async function explain(i) {
  const why = $("#soc-why", root);
  const edge = i.record ? (i.flow_ids || [])[0] : (i.sample_edges || [])[0];
  if (edge == null) { why.innerHTML = `<div class="empty">No sample flow available for this incident.</div>`; return; }
  let ex;
  try {
    // a live flow is explained inside the context it was scored in (its chunk plus the site's last two minutes)
    ex = i.record ? await get(`/live/explain/${edge}`) : await get(`/explain/${windowOf(i)}/${edge}?model=${current.model}`);
  } catch (e) { showError(why, e, { what: "the explanation" }); return; }
  if (selected !== uidOf(i)) return;               // the analyst moved on while this was loading
  const st = ex.structure;
  why.innerHTML = `
    <div class="callout">${esc(ex.summary)}</div>
    <div style="margin-top:10px">
      <p class="sub" style="margin-bottom:4px">What pushed the decision —
        <span style="color:var(--critical)">red towards</span> the verdict,
        <span style="color:var(--m-ours)">blue against</span> it</p>
      <div class="chart short"><canvas id="soc-attr" aria-label="feature attribution for this flow"></canvas></div>
      <p class="sub" style="margin:12px 0 4px">Network context</p>
      ${table([{ title: "Fact", key: "k" }, { title: "Value", key: "v", num: true }], [
        { k: "Source host talks to", v: `${int(st.source_distinct_peers)} hosts` },
        { k: "Flows from source", v: int(st.source_flows) },
        ...(st.source_distinct_ports != null ? [{ k: "Distinct ports it targeted", v: int(st.source_distinct_ports) }] : []),
        { k: "Destination hears from", v: `${int(st.destination_distinct_peers)} hosts` },
        { k: "Flows to destination", v: int(st.destination_flows) },
        { k: "Evidence from neighbouring flows", v: pct(ex.context_share, 0) },
      ])}
      <p class="note">Example flow <span class="mono">${esc(ex.src_ip)} → ${esc(ex.dst_ip)}</span> · model says
        <b>${esc(ex.predicted_label)}</b> (${pct(ex.confidence, 0)}) · ${ex.true_label != null
          ? `ground truth <b>${esc(ex.true_label)}</b>`
          : `live traffic: no ground truth${ex.predicted_when_scored && ex.predicted_when_scored !== ex.predicted_label
              ? ` · when scored it said ${esc(ex.predicted_when_scored)}; the model has been taught since` : ""}`}</p>
    </div>`;
  const f = ex.features;
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v);
  mount($("#soc-attr", root), {
    type: "bar",
    data: { labels: f.map((x) => x.label),
            datasets: [{ label: "attribution", data: f.map((x) => x.attribution), borderRadius: 4,
                         backgroundColor: f.map((x) => css(x.attribution > 0 ? "--critical" : "--m-ours")) }] },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
                 tooltip: { callbacks: { label: (c) => {
                   const x = f[c.dataIndex];
                   return ` value ${x.value == null ? "–" : fmtValue(x.value)} · ${x.direction} the verdict`;
                 } } } },
      scales: { x: { grid: { color: css("--grid") }, ticks: { display: false } }, y: { grid: { display: false } } },
    },
  });
}

/* ------------------------------------------------------------------ decisions */
// the database stores UTC; SQLite drops the offset, so treat a bare timestamp as UTC
function localTime(iso) {
  if (!iso) return "–";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + "Z");
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

async function decide(i, decision) {
  const p = i.proposed || {};
  const rule = $("#soc-rule", root)?.textContent || "";
  const ok = await confirmDialog({
    title: decision === "approve" ? "Approve this containment?" : "Reject this containment?",
    tag: "dry run",
    body: decision === "approve"
      ? `This records approval of “${ACTION_TEXT[p.action] || p.action}” for ${p.target}. `
        + "The rule below is NOT sent to any firewall — the decision is stored as a dry run."
      : `This records that incident #${numberOf(i)} was rejected. Nothing was executed either way.`,
    detail: decision === "approve" ? rule : "",
    confirmLabel: decision === "approve" ? "Record approval" : "Record rejection",
    danger: decision === "reject",
  });
  if (!ok) return;

  const btns = $$("#soc-decide .btn", root);
  btns.forEach((b) => { b.disabled = true; });
  const analyst = $("#soc-analyst", root).value.trim() || "analyst";
  prefs.set("analyst", analyst);
  try {
    const a = i.record
      ? await post("/live/actions", { site: i.site, category: i.category, target: p.target,
                                      minutes: Number($("#soc-minutes", root).value) })
      : await post("/actions", { window_id: windowOf(i), incident_id: i.incident_id, model: current.model,
                                 threshold: current.threshold, category: i.category, target: p.target });
    const d = a.status === "proposed"
      ? await post(`/actions/${a.id}/decision`, { decision, analyst, note: $("#soc-note", root).value.trim() || null })
      : a;                                 // already decided earlier: show that decision instead of a second one
    if (a.status === "proposed") toast(`Incident #${numberOf(i)}: ${ACTION_TEXT[d.action] || d.action} ${d.status} (dry run)`);
    else toast(`Incident #${numberOf(i)} was already ${d.status} by ${d.decided_by || "an analyst"}`);
    $("#soc-decide", root).innerHTML = `<span class="tag ${d.status === "approved" ? "good" : "bad"}">${esc(d.status)}</span>
      <span class="muted">by ${esc(d.decided_by || "—")} · ${esc(localTime(d.decided_at))} · recorded in the decision log
      <span class="tag dry">dry run</span></span>`;
    log(currentFilter());
  } catch (e) {
    btns.forEach((b) => { b.disabled = false; });
    toast(`Could not record the decision: ${e.message}`);
  }
}

async function log(status) {
  const el = $("#soc-log", root);
  let rows;
  try { rows = await get(`/actions${status ? `?status=${status}` : ""}`); }
  catch (e) { showError(el, e, { what: "the decision log" }); return; }
  if (!rows.length) {
    el.innerHTML = `<div class="empty"><span class="title">No decisions yet</span>Approve or reject an incident above and it appears here.</div>`;
    return;
  }
  const tag = (s) => `<span class="tag ${s === "approved" ? "good" : s === "rejected" ? "bad" : "warn"}">${esc(s)}</span>`;
  el.innerHTML = table([
    { title: "When (local time)", value: (r) => localTime(r.decided_at || r.created_at) },
    { title: "Source", value: (r) => (r.site ? `live · ${r.site}` : `recorded window #${r.window_id} / ${r.incident_id}`) },
    { title: "Category", html: (r) => `<span class="swatch" style="background:${catColor(r.category)}"></span>${esc(r.category)}` },
    { title: "Action", value: (r) => ACTION_TEXT[r.action] || r.action },
    { title: "Target", html: (r) => `<span class="mono">${esc(r.target)}</span>` },
    { title: "Decision", html: (r) => tag(r.status) },
    { title: "By", value: (r) => r.decided_by || "–" },
    { title: "Note", value: (r) => r.note || "" },
  ], rows);
  makeSortable(el);
}
