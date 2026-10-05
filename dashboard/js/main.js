// App shell: tab routing (hash-based), global dataset/mode context, health pills, theme.
import { $, $$, esc, get, onContextChange, prefs, setApiKey, setContext, state, toast } from "./lib/core.js";
import { applyDefaults } from "./lib/charts.js";

const VIEWS = {
  overview: () => import("./views/overview.js"),
  soc: () => import("./views/soc.js"),
  live: () => import("./views/live.js"),
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
  $$(".tab").forEach((t) => t.classList.toggle("on", t.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === `view-${name}`));
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

function initControls() {
  syncSeg("ds-seg", state.dataset); syncSeg("mode-seg", state.mode);
  $$("#ds-seg button").forEach((b) => b.addEventListener("click", () => { syncSeg("ds-seg", b.dataset.v); setContext({ dataset: b.dataset.v }); }));
  $$("#mode-seg button").forEach((b) => b.addEventListener("click", () => { syncSeg("mode-seg", b.dataset.v); setContext({ mode: b.dataset.v }); }));
  $$(".tab").forEach((t) => t.addEventListener("click", () => { location.hash = t.dataset.view; }));
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
  onContextChange(() => Object.values(loaded).forEach((m) => m.refresh && m.refresh()));
  const help = (open) => {
    $("#help").classList.toggle("hidden", !open); $("#help-scrim").classList.toggle("hidden", !open);
    if (open) prefs.set("helpSeen", "1");
  };
  $("#help-btn").addEventListener("click", () => help(true));
  $("#help-close").addEventListener("click", () => help(false));
  $("#help-scrim").addEventListener("click", () => help(false));
  const order = $$(".tab").map((t) => t.dataset.view);
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) return;
    if (e.key === "Escape") help(false);
    else if (e.key === "?") help($("#help").classList.contains("hidden"));
    else if (/^[0-9]$/.test(e.key)) { const i = e.key === "0" ? 9 : Number(e.key) - 1; if (order[i]) location.hash = order[i]; }
  });
  if (!prefs.get("helpSeen", "")) help(true);
}

function pill(id, ok, text) {
  const el = $(id); const dot = el.querySelector(".dot");
  dot.className = `dot ${ok === true ? "ok" : ok === false ? "bad" : "warn"}`;
  if (text) (el.querySelector("span") || el).lastChild.textContent = text;
}

/** One line at the top of the page when something is wrong, naming what still works. */
function banner(html, kind = "warn") {
  const el = $("#banner");
  if (!html) { el.classList.add("hidden"); el.innerHTML = ""; return; }
  if (el.dataset.html === html) return;                 // do not re-render on every poll
  el.dataset.html = html; el.className = `banner ${kind}`;
  el.innerHTML = `${html}<button class="icon-btn small" id="banner-x" title="Dismiss">✕</button>`;
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
    const txt = live ? `Stream ${d.position}/${d.total || "…"}` : `Stream ${d.status || "idle"}`;
    pill("#pill-stream", live ? true : null, txt);
  } catch { /* ignore */ }
}

applyDefaults();
initControls();
show(location.hash.slice(1) || "overview");
health();
setInterval(health, 4000);
