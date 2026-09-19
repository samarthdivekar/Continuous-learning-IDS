// App shell: tab routing (hash-based), global dataset/mode context, health pills, theme.
import { $, $$, get, onContextChange, prefs, setContext, state } from "./lib/core.js";
import { applyDefaults } from "./lib/charts.js";

const VIEWS = {
  overview: () => import("./views/overview.js"),
  soc: () => import("./views/soc.js"),
  live: () => import("./views/live.js"),
  explorer: () => import("./views/explorer.js"),
  compare: () => import("./views/compare.js"),
  drift: () => import("./views/drift.js"),
  general: () => import("./views/general.js"),
  classify: () => import("./views/classify.js"),
  trust: () => import("./views/trust.js"),
  repro: () => import("./views/repro.js"),
};
const loaded = {};

async function show(name) {
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

function syncSeg(id, value) { $$(`#${id} button`).forEach((b) => b.classList.toggle("on", b.dataset.v === value)); }

function initControls() {
  syncSeg("ds-seg", state.dataset); syncSeg("mode-seg", state.mode);
  $$("#ds-seg button").forEach((b) => b.addEventListener("click", () => { syncSeg("ds-seg", b.dataset.v); setContext({ dataset: b.dataset.v }); }));
  $$("#mode-seg button").forEach((b) => b.addEventListener("click", () => { syncSeg("mode-seg", b.dataset.v); setContext({ mode: b.dataset.v }); }));
  $$(".tab").forEach((t) => t.addEventListener("click", () => { location.hash = t.dataset.view; }));
  window.addEventListener("hashchange", () => show(location.hash.slice(1)));
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

async function health() {
  try {
    const h = await get("/health");
    pill("#pill-api", true);
    pill("#pill-db", h.database);
    const ml = h.ml || {};
    pill("#pill-ml", ml.status === "ok" || ml.status === "in-process");
    $("#pill-ml").title = `${ml.device || "?"}${ml.gpu ? " · " + ml.gpu : ""} · models: ${(ml.models_loaded || []).join(", ")}`;
  } catch {
    pill("#pill-api", false); pill("#pill-ml", null); pill("#pill-db", null);
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
