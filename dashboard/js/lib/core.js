// Shared state, API client, formatting, model colours and small DOM helpers.
export const API = window.API_BASE || "/api";

export const state = {
  dataset: localGet("ds", "cicids2017"),
  // The console shows the multiclass task sequence only: the binary sequence ties with the per-flow model on
  // CIC-IDS2017 and was withdrawn for CSE-CIC-IDS2018 (one seed). Binary leave-one-attack-out (unseen attacks)
  // is a separate experiment and is always shown.
  mode: "multiclass",
  compare: localGet("compare", "0") === "1",   // off = one model; on = every ablation
  listeners: new Set(),
};
// CSE-CIC-IDS2018 binary was run with a single seed, so its task-sequence results are withdrawn
// (README, results §6): the console never offers that combination. Its unseen-attack (binary) results
// are a separate experiment and stay.
export const withdrawn = (dataset, mode) => dataset === "csecicids2018" && mode === "binary";
if (withdrawn(state.dataset, state.mode)) state.mode = "multiclass";
export function onContextChange(fn) { state.listeners.add(fn); }
export function setContext(patch) {
  Object.assign(state, patch);
  if (withdrawn(state.dataset, state.mode)) state.mode = "multiclass";
  localSet("ds", state.dataset); localSet("mode", state.mode); localSet("compare", state.compare ? "1" : "0");
  state.listeners.forEach((fn) => { try { fn(); } catch (e) { console.error(e); } });
}

function localGet(k, d) { try { return localStorage.getItem("gnnids." + k) || d; } catch { return d; } }
function localSet(k, v) { try { localStorage.setItem("gnnids." + k, v); } catch { /* private mode */ } }
export const prefs = { get: localGet, set: localSet };

// The API needs a key only when the server was started with GNNIDS_API_KEY. The console asks for it
// once (main.js) and remembers it in this browser; it is sent only in the X-API-Key header, never in a URL.
export const apiKey = () => localGet("apiKey", "");
export function setApiKey(k) { localSet("apiKey", k || ""); }
const authHeaders = () => (apiKey() ? { "X-API-Key": apiKey() } : {});

async function request(path, init) {
  const r = await fetch(`${API}${path}`, { ...init, headers: { ...(init?.headers || {}), ...authHeaders() } });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    const err = new Error(j.detail || `${r.status} ${path}`);
    err.status = r.status;
    if (r.status === 401) err.needsKey = true;
    throw err;
  }
  return r.json();
}
export const get = (path) => request(path, {});
export const post = (path, body) => request(path, { method: "POST", headers: { "Content-Type": "application/json" },
                                                    body: JSON.stringify(body || {}) });
/** Open or download an API response in a new tab without putting the key in the URL. */
export async function openApi(path, { filename } = {}) {
  const r = await fetch(`${API}${path}`, { headers: authHeaders() });
  if (!r.ok) { toast(`${r.status}: could not open ${path}`); return; }
  const blob = await r.blob();
  if (filename) { download(filename, blob); return; }
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
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
  // gnn_ewc_replay_topo (topology augmentation) is an appendix experiment, discussed in the README only:
  // it is deliberately absent here, and `known()` keeps it out of tables built from results files.
  gnn_joint:       { label: "GNN joint (upper bound)",   short: "GNN joint", var: "--m-joint", dashed: true },
  ffnn_joint:      { label: "FFNN joint (upper bound)",  short: "FFNN joint", var: "--muted", dashed: true },
};
export const PRIMARY = "gnn_ewc_replay";                       // the product's model
export const HEADLINE = ["gnn_ewc_replay", "gnn_naive", "xgboost_static", "ffnn_ewc_replay"];
// What a chart should draw: the story (ours vs forgetting vs static) or every ablation.
export const STORY = ["gnn_ewc_replay", "gnn_naive", "xgboost_static"];
export const shownModels = (available) => {
  const keep = state.compare ? Object.keys(MODELS) : STORY;
  const picked = keep.filter((m) => available.includes(m));
  return picked.length ? picked : available.slice(0, state.compare ? available.length : 3);
};
export const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
export const color = (m) => css((MODELS[m] || { var: "--muted" }).var);
export const label = (m) => (MODELS[m] || { label: m }).label;
export const known = (models) => models.filter((m) => m in MODELS);   // drop appendix-only models

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
/** Download helpers: every table and chart can leave the browser as CSV or PNG. */
export function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function downloadCsv(name, rows) {
  if (!rows?.length) { toast("nothing to export"); return; }
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const needsQuote = /[",\r\n]/;
  const cell = (v) => (v == null ? "" : needsQuote.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const csv = [cols.join(","), ...rows.map((r) => cols.map((c) => cell(r[c])).join(","))].join("\r\n");
  download(name, new Blob([csv], { type: "text/csv;charset=utf-8" }));
}
export function downloadChart(canvas, name) {
  if (!canvas) { toast("no chart to export"); return; }
  const out = document.createElement("canvas");
  out.width = canvas.width; out.height = canvas.height;
  const ctx = out.getContext("2d");
  ctx.fillStyle = css("--page") || "#fff";           // charts are transparent; PNGs should not be
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(canvas, 0, 0);
  out.toBlob((b) => download(name, b));
}
/** A small ⤓ menu for a card: CSV of the rows, PNG of the chart. */
/** Put a ⤓ button in the card that contains `el`: CSV of its rows, PNG of its chart. */
export function attachExport(el, { rows, canvas, name }) {
  const card = el?.closest?.(".card");
  const head = card?.querySelector("h3");
  if (!head) return;
  const headRow = card.querySelector(".card-head");
  let tools = card.querySelector(".card-tools");
  if (!tools) {
    tools = document.createElement("span");
    // inside a header row it sits at the end; otherwise it floats in the card's top-right corner
    tools.className = headRow ? "card-tools" : "card-tools floating";
    if (headRow) tools.style.marginLeft = "auto";
    (headRow || card).appendChild(tools);
  }
  if (tools.querySelector(`[data-export="${name}"]`)) return;      // already there
  const btn = document.createElement("button");
  btn.className = "icon-btn small";
  btn.dataset.export = name;
  btn.textContent = "⤓";
  btn.title = `Download this panel${rows ? " (CSV" : ""}${rows && canvas ? " + PNG)" : rows ? ")" : canvas ? " (PNG)" : ""}`;
  btn.addEventListener("click", () => {
    const r = typeof rows === "function" ? rows() : rows;
    if (r?.length) downloadCsv(`${name}.csv`, r);
    const c = typeof canvas === "function" ? canvas() : canvas;
    if (c) downloadChart(c, `${name}.png`);
  });
  tools.appendChild(btn);
}

export const modelCell = (m) => `<span class="model-cell"><span class="swatch" style="background:${color(m)}"></span>${esc(label(m))}</span>`;

// sequential blue scale for heatmaps (value in [0,1])
export function heatColor(v) {
  if (v == null || Number.isNaN(v)) return "transparent";
  const a = 0.08 + 0.82 * Math.max(0, Math.min(1, v));
  return `color-mix(in srgb, ${css("--m-ours")} ${Math.round(a * 100)}%, transparent)`;
}
