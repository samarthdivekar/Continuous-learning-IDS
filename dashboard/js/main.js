// App shell: sidebar routing (hash-based), global dataset/mode context, service status, theme.
import { $, $$, esc, get, onContextChange, post, prefs, setApiKey, setContext, state, toast, withdrawn } from "./lib/core.js";
import { applyDefaults } from "./lib/charts.js";
import * as tour from "./lib/tour.js";
import * as palette from "./lib/palette.js";

const VIEWS = {
  overview: () => import("./views/overview.js"),
  soc: () => import("./views/soc.js"),
  live: () => import("./views/live.js"),
  sites: () => import("./views/sites.js"),
  explorer: () => import("./views/explorer.js"),
  classify: () => import("./views/classify.js"),
  models: () => import("./views/models.js"),
  adapt: () => import("./views/adapt.js"),
  repro: () => import("./views/repro.js"),
};
const loaded = {};

async function show(name) {
  if (LEGACY[name]) name = LEGACY[name];          // old bookmarks keep working
  if (!VIEWS[name]) name = "overview";
  $$(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("on", on);
    t.setAttribute("aria-selected", String(on));
    if (on) {                                       // the top bar says where you are
      $("#crumb-group").textContent = t.dataset.group || "";
      $("#crumb-title").textContent = t.querySelector(".nav-label")?.textContent || name;
    }
  });
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `view-${name}`));
  document.body.classList.remove("nav-open");      // a choice on the phone drawer closes it
  $("#nav-scrim").classList.add("hidden");
  const el = $(`#view-${name}`);
  if (!loaded[name]) {
    el.innerHTML = `<div class="empty pulse">Loading…</div>`;
    const mod = await VIEWS[name]();
    loaded[name] = mod;
    await mod.mount(el);
  } else if (loaded[name].activate) {
    loaded[name].activate();
  }
}

const LEGACY = { compare: "models", general: "models", drift: "adapt", trust: "adapt" };

function syncSeg(id, value) { $$(`#${id} button`).forEach((b) => b.classList.toggle("on", b.dataset.v === value)); }

/** Keep the switches honest: Binary is unavailable for CSE-CIC-IDS2018 (see core.js `withdrawn`). */
function syncContext() {
  syncSeg("ds-seg", state.dataset); syncSeg("mode-seg", state.mode);
  const binary = $('#mode-seg button[data-v="binary"]');
  const off = withdrawn(state.dataset, "binary");
  binary.disabled = off;
  binary.title = off ? "Withdrawn for CSE-CIC-IDS2018: the binary task sequence had one seed" : "";
}

function initControls() {
  syncContext();
  $$("#ds-seg button").forEach((b) => b.addEventListener("click", () => { syncSeg("ds-seg", b.dataset.v); setContext({ dataset: b.dataset.v }); }));
  $$("#mode-seg button").forEach((b) => b.addEventListener("click", () => { syncSeg("mode-seg", b.dataset.v); setContext({ mode: b.dataset.v }); }));
  $$(".tab").forEach((t) => t.addEventListener("click", () => { location.hash = t.dataset.view; }));
  const drawer = (open) => {                         // narrow screens: the sidebar is a drawer
    document.body.classList.toggle("nav-open", open);
    $("#nav-scrim").classList.toggle("hidden", !open);
  };
  $("#menu-btn").addEventListener("click", () => drawer(!document.body.classList.contains("nav-open")));
  $("#nav-scrim").addEventListener("click", () => drawer(false));
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
  const cmp = $("#compare-toggle");
  cmp.checked = state.compare;
  cmp.addEventListener("change", () => setContext({ compare: cmp.checked }));
  const theme = prefs.get("theme", "dark");
  document.documentElement.dataset.theme = theme;
  $("#theme-btn").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = t; prefs.set("theme", t);
    applyDefaults();
    Object.values(loaded).forEach((m) => m.refresh && m.refresh());
  });
  onContextChange(syncContext);
  onContextChange(() => Object.values(loaded).forEach((m) => m.refresh && m.refresh()));
  const help = (open) => {
    $("#help").classList.toggle("hidden", !open); $("#help-scrim").classList.toggle("hidden", !open);
    if (open) prefs.set("helpSeen", "1");
  };
  const present = $("#present-btn");
  const setPresentation = (on) => {
    document.documentElement.dataset.presentation = on ? "on" : "off";
    present.classList.toggle("on", on);
    present.setAttribute("aria-pressed", String(on));
    prefs.set("presentation", on ? "1" : "0");
    applyDefaults();
    Object.values(loaded).forEach((m) => m.refresh && m.refresh());
  };
  setPresentation(prefs.get("presentation", "0") === "1");
  present.addEventListener("click", () => setPresentation(document.documentElement.dataset.presentation !== "on"));
  $("#tour-btn").addEventListener("click", () => { help(false); tour.start(); });
  $("#help-btn").addEventListener("click", () => { tour.stop(); help(true); });
  $("#help-close").addEventListener("click", () => help(false));
  $("#help-scrim").addEventListener("click", () => help(false));
  const order = $$(".tab").map((t) => t.dataset.view);

  // ---- command palette -------------------------------------------------
  const go = (view) => { location.hash = view; };
  const TAB_KEYWORDS = {
    overview: ["results", "summary", "headline", "verdict", "kpi"],
    soc: ["incidents", "alerts", "triage", "queue", "approve", "reject", "containment", "explain", "report"],
    live: ["stream", "demo", "replay", "retrain", "adapt", "drift events"],
    sites: ["live sites", "sensor", "real traffic", "pcap", "capture", "lan", "label", "teach", "wifi"],
    explorer: ["graph", "network", "topology", "hosts", "edges", "window"],
    classify: ["predict", "csv", "flows", "upload", "pcap"],
    models: ["accuracy", "forgetting", "bwt", "unseen", "leave-one-attack-out", "ip leakage", "confusion", "recall"],
    adapt: ["drift", "adwin", "retraining", "novelty", "open set", "conformal", "abstention", "alert load", "labels"],
    repro: ["seeds", "lambda", "sweep", "tuning", "metadata", "reproduce", "commit"],
  };
  const tabActions = $$(".tab").map((t) => ({
    label: `Go to ${t.querySelector(".nav-label").textContent.trim()}`, group: "page",
    keywords: TAB_KEYWORDS[t.dataset.view] || [], run: () => go(t.dataset.view),
  }));
  const streamAction = async (path, label) => {
    try {
      const r = await post(path, path === "/demo/start" ? { delay_seconds: 0.3, eval_every: 10 } : {});
      toast(r?.accepted === false ? r.reason || `${label} refused` : `${label}`);
      go("live");
    } catch (e) { toast(`${label} failed: ${e.message}`); }
  };
  palette.setActions([
    ...tabActions,
    { label: "Dataset: CIC-IDS2017", group: "context",
      run: () => { syncSeg("ds-seg", "cicids2017"); setContext({ dataset: "cicids2017" }); } },
    { label: "Dataset: CSE-CIC-IDS2018", group: "context",
      run: () => { syncSeg("ds-seg", "csecicids2018"); setContext({ dataset: "csecicids2018" }); } },
    { label: "Labels: multiclass (named attacks)", group: "context",
      run: () => { syncSeg("mode-seg", "multiclass"); setContext({ mode: "multiclass" }); } },
    { label: "Labels: binary (attack vs benign)", group: "context",
      run: () => { syncSeg("mode-seg", "binary"); setContext({ mode: "binary" }); } },
    { label: () => `Compare models: turn ${state.compare ? "off" : "on"}`, group: "context",
      run: () => { const on = !state.compare; $("#compare-toggle").checked = on; setContext({ compare: on }); } },
    { label: "Start the live stream", group: "stream", run: () => streamAction("/demo/start", "stream started") },
    { label: "Retrain now", group: "stream", run: () => streamAction("/retrain", "adaptation requested") },
    { label: "Stop the live stream", group: "stream", run: () => streamAction("/demo/stop", "stream stopped") },
    { // a bare number jumps straight to that incident in the queue
      label: (q) => `Open incident #${q || "…"}`, group: "incident", priority: 10,
      match: (q) => /^\d+$/.test(q),
      run: (q) => {
        go("soc");
        const id = Number(q);
        const tryOpen = (left) => {
          if (loaded.soc?.openIncident?.(id)) return;
          if (left) setTimeout(() => tryOpen(left - 1), 400);
          else toast(`Incident #${id} is not in the current queue — load a window first`);
        };
        setTimeout(() => tryOpen(12), 300);
      } },
    { label: () => `Theme: switch to ${document.documentElement.dataset.theme === "dark" ? "light" : "dark"}`,
      group: "view", run: () => $("#theme-btn").click() },
    { label: () => `Presentation mode: turn ${document.documentElement.dataset.presentation === "on" ? "off" : "on"}`,
      group: "view", run: () => present.click() },
    { label: "Open help and glossary", group: "view", run: () => help(true) },
    { label: "Start the guided tour", group: "view", run: () => { help(false); tour.start(); } },
  ]);
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); palette.open(); }
  });
  $("#search-btn").addEventListener("click", () => palette.open());
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || palette.isOpen()
        || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
    if (e.key === "Escape") { help(false); drawer(false); }
    else if (e.key === "?") help($("#help").classList.contains("hidden"));
    else if (/^[0-9]$/.test(e.key)) { const i = e.key === "0" ? 9 : Number(e.key) - 1; if (order[i]) location.hash = order[i]; }
  });
  if (!prefs.get("helpSeen", "")) help(true);
}

/** One row of the sidebar's service status: a coloured dot and a one-word state. */
function pill(id, ok, text) {
  const el = $(id);
  el.querySelector(".dot").className = `dot ${ok === true ? "ok" : ok === false ? "bad" : "warn"}`;
  el.querySelector(".status-val").textContent = text || (ok === true ? "online" : ok === false ? "offline" : "unknown");
}

/** One line at the top of the page when something is wrong, naming what still works. */
function banner(html, kind = "warn") {
  const el = $("#banner");
  // clearing also forgets the last message, so the same problem shows again if it returns
  if (!html) { el.classList.add("hidden"); el.innerHTML = ""; el.dataset.html = ""; return; }
  if (el.dataset.html === html) return;                 // do not re-render on every poll
  el.dataset.html = html; el.dataset.dismissed = ""; el.className = `banner ${kind}`;
  el.innerHTML = `<div class="banner-msg">${html}</div><button class="icon-btn small" id="banner-x" title="Dismiss">✕</button>`;
  $("#banner-x").addEventListener("click", () => { el.classList.add("hidden"); el.dataset.dismissed = "1"; });
}

async function askForKey() {
  const key = window.prompt("This API needs a key (GNNIDS_API_KEY on the server). Paste it to continue:");
  if (key) { setApiKey(key.trim()); location.reload(); }
}

async function health() {
  try {
    const h = await get("/health");
    pill("#pill-api", true);
    pill("#pill-db", h.database);
    const ml = h.ml || {};
    const mlOk = ml.status === "ok" || ml.status === "in-process";
    pill("#pill-ml", mlOk);
    if ($("#banner").dataset.dismissed !== "1") {
      banner(mlOk ? "" : `<b>Live model unavailable.</b> Overview, Models, Adaptation &amp; trust and Reproducibility still
        work (they read saved results). Incident queue, Live stream, Graph explorer and Classify need the model service.
        <span class="muted">${esc(String(ml.detail || "").slice(0, 140))}</span>`);
    }
    $("#pill-ml").title = `${ml.device || "?"}${ml.gpu ? " · " + ml.gpu : ""} · models: ${(ml.models_loaded || []).join(", ")}`;
  } catch (e) {
    pill("#pill-api", false); pill("#pill-ml", null); pill("#pill-db", null);
    if (e.needsKey) { banner("<b>API key required.</b> The server was started with authentication enabled.", "bad"); askForKey(); }
    else if ($("#banner").dataset.dismissed !== "1") banner("<b>API unreachable.</b> Start it with <span class=\"mono\">scripts/run_stack.ps1</span>.", "bad");
  }
  try {
    const d = await get("/demo/status");
    const live = d.alive;
    $("#live-badge").classList.toggle("hidden", !live);
    const txt = live ? `${d.position}/${d.total || "…"}` : `${d.status || "idle"}`;
    pill("#pill-stream", live ? true : null, txt);
  } catch { /* ignore */ }
}

applyDefaults();
initControls();
show(location.hash.slice(1) || "overview");
health();
setInterval(health, 4000);
