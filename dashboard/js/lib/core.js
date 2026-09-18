// Shared state, API client, formatting, model colours and small DOM helpers.
export const API = window.API_BASE || "/api";

export const state = {
  dataset: localGet("ds", "cicids2017"),
  mode: localGet("mode", "multiclass"),
  listeners: new Set(),
};
export function onContextChange(fn) { state.listeners.add(fn); }
export function setContext(patch) {
  Object.assign(state, patch);
  localSet("ds", state.dataset); localSet("mode", state.mode);
  state.listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
}

function localGet(k, d) { try { return localStorage.getItem("gnnids." + k) || d; } catch { return d; } }
function localSet(k, v) { try { localStorage.setItem("gnnids." + k, v); } catch { /* private mode */ } }
export const prefs = { get: localGet, set: localSet };

export async function get(path) {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    const err = new Error(j.detail || `${r.status} ${path}`);
    err.status = r.status; throw err;
  }
  return r.json();
}
export async function post(path, body) {
  const r = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
                                           body: JSON.stringify(body || {}) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(j.detail || r.status); e.status = r.status; throw e; }
  return j;
}

// ---------------------------------------------------------------- models
export const MODELS = {
  gnn_ewc_replay:  { label: "GNN + EWC + replay (ours)", short: "Ours", var: "--m-ours" },
  gnn_naive:       { label: "GNN naive retrain",         short: "GNN naive", var: "--m-gnn-naive" },
  xgboost_static:  { label: "XGBoost static",            short: "XGBoost", var: "--m-xgb" },
  ffnn_ewc_replay: { label: "FFNN + EWC + replay",       short: "FFNN+EWC+R", var: "--m-ffnn" },
  ffnn_naive:      { label: "FFNN naive retrain",        short: "FFNN naive", var: "--m-ffnn-naive" },
  gnn_ewc:         { label: "GNN + EWC only",            short: "GNN EWC", var: "--m-gnn-ewc" },
  gnn_replay:      { label: "GNN + replay only",         short: "GNN replay", var: "--m-gnn-replay" },
  gnn_joint:       { label: "GNN joint (upper bound)",   short: "GNN joint", var: "--m-joint", dashed: true },
  ffnn_joint:      { label: "FFNN joint (upper bound)",  short: "FFNN joint", var: "--muted", dashed: true },
};
export const HEADLINE = ["gnn_ewc_replay", "gnn_naive", "xgboost_static", "ffnn_ewc_replay"];
export const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const color = (m) => css((MODELS[m] || { var: "--muted" }).var);
export const label = (m) => (MODELS[m] || { label: m }).label;

export const CATEGORY_COLORS = {
  Benign: "--benign-edge", BruteForce: "--m-ffnn", DoS: "--m-gnn-naive", WebAttack: "--m-ffnn-naive",
  Infiltration: "--m-gnn-replay", Botnet: "--m-xgb", PortScan: "--warn", DDoS: "--critical", Attack: "--critical",
};
export const catColor = (c) => css(CATEGORY_COLORS[c] || "--muted");

// ---------------------------------------------------------------- format
export const pct = (v, d = 1) => (v == null || Number.isNaN(v) ? "–" : `${(v * 100).toFixed(v > 0 && v < 0.01 ? Math.max(d, 2) : d)}%`);
export const f3 = (v) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(3));
export const int = (v) => (v == null ? "–" : Number(v).toLocaleString());
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------------------------------------------------------------- DOM
export function h(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function toast(msg, ms = 3500) {
  const el = h(`<div class="toast">${esc(msg)}</div>`);
  document.body.appendChild(el);
  setTimeout(() => el.remove(), ms);
}
export function emptyState(el, msg) { el.innerHTML = `<div class="empty">${msg}</div>`; }

export function table(columns, rows, { highlight } = {}) {
  const th = columns.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.title)}</th>`).join("");
  const tr = rows.map((r) => `<tr class="${highlight && highlight(r) ? "hl" : ""}">${columns.map((c) =>
    `<td class="${c.num ? "num" : ""}">${c.html ? c.html(r) : esc(c.value ? c.value(r) : r[c.key])}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table class="data"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}
export const modelCell = (m) => `<span class="swatch" style="background:${color(m)}"></span>${esc(label(m))}`;

// sequential blue scale for heatmaps (value in [0,1])
export function heatColor(v) {
  if (v == null || Number.isNaN(v)) return "transparent";
  const a = 0.08 + 0.82 * Math.max(0, Math.min(1, v));
  return `color-mix(in srgb, ${css("--m-ours")} ${Math.round(a * 100)}%, transparent)`;
}
