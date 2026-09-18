// Graph Explorer: browse every window graph, colour by ground truth or by a model's mistakes.
import { $, catColor, esc, get, HEADLINE, int, label, pct, prefs, toast } from "../lib/core.js";
import { GraphView } from "../lib/graphview.js";

let root, view, catalog = [], current = null, serviceDataset = null;

export async function mount_(el) {
  root = el;
  root.innerHTML = `
    <div class="view-head"><div><h2>Graph explorer</h2>
      <p>Each 5,000-flow window becomes a graph: <b>hosts are nodes, flows are edges</b>. Scans fan out from one host, DDoS
      converges on one victim — structure a per-flow model cannot see. Scroll to zoom, drag to pan, hover a host for details.</p></div></div>
    <div class="grid g-8-4">
      <div class="card">
        <div class="card-head"><div><h3 id="ex-title">Select a window</h3><p class="sub" id="ex-sub">–</p></div>
          <div class="toolbar">
            <div class="seg" id="ex-mode"><button data-v="truth" class="on">Ground truth</button><button data-v="errors">Model errors</button></div>
            <select id="ex-model">${HEADLINE.map((m) => `<option value="${m}">${esc(label(m))}</option>`).join("")}</select>
            <label class="inline">Hosts <input type="range" id="ex-nodes" min="30" max="400" step="10" value="${prefs.get("ex.nodes", "150")}"><span id="ex-nodes-v" class="num"></span></label>
          </div></div>
        <div class="graph-stage" id="ex-stage"></div>
        <div class="legend" id="ex-legend" style="margin-top:10px"></div>
      </div>
      <div class="grid" style="gap:16px;align-content:start">
        <div class="card"><h3>Window stats</h3><div id="ex-stats"><div class="empty">Pick a window from the list.</div></div></div>
        <div class="card"><div class="card-head"><h3>Windows</h3>
          <div class="toolbar"><select id="ex-task"><option value="">all tasks</option></select>
          <select id="ex-split"><option value="test">test</option><option value="val">val</option><option value="train">train</option><option value="">all</option></select>
          <label class="inline"><input type="checkbox" id="ex-attack" checked> attacks only</label></div></div>
          <div class="window-list" id="ex-list"></div></div>
      </div>
    </div>`;
  view = new GraphView($("#ex-stage", root));
  const nodes = $("#ex-nodes", root);
  const syncNodes = () => { $("#ex-nodes-v", root).textContent = nodes.value; };
  syncNodes();
  nodes.addEventListener("input", syncNodes);
  nodes.addEventListener("change", () => { prefs.set("ex.nodes", nodes.value); if (current) load(current); });
  root.querySelectorAll("#ex-mode button").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll("#ex-mode button").forEach((x) => x.classList.toggle("on", x === b));
    view.mode = b.dataset.v; if (current) load(current);
  }));
  $("#ex-model", root).addEventListener("change", () => { if (current && view.mode === "errors") load(current); });
  ["#ex-task", "#ex-split", "#ex-attack"].forEach((s) => $(s, root).addEventListener("change", renderList));
  try {
    const h = await get("/health");
    serviceDataset = h.ml?.dataset;
    catalog = await get("/windows/catalog");
  } catch (e) {
    $("#ex-list", root).innerHTML = `<div class="empty">${esc(e.message)}</div>`; return;
  }
  const tasks = [...new Map(catalog.map((w) => [w.task_id, w.task_category])).entries()];
  $("#ex-task", root).innerHTML += tasks.map(([t, c]) => `<option value="${t}">${t + 1}. ${esc(c)}</option>`).join("");
  renderList();
  const first = catalog.find((w) => w.split === "test" && w.n_attack > 500) || catalog[0];
  if (first) load(first.window_id);
}
export { mount_ as mount };
export function refresh() { if (current) load(current); }

function renderList() {
  const t = $("#ex-task", root).value, s = $("#ex-split", root).value, a = $("#ex-attack", root).checked;
  const rows = catalog.filter((w) => (t === "" || w.task_id === Number(t)) && (s === "" || w.split === s) && (!a || w.n_attack > 0));
  $("#ex-list", root).innerHTML = rows.length ? rows.map((w) => `
    <button data-w="${w.window_id}" class="${w.window_id === current ? "on" : ""}">
      <span class="num">#${w.window_id}</span>
      <span>${esc(w.task_category)} · ${w.split}${w.top_attack ? ` · <span style="color:${catColor(w.top_attack)}">${esc(w.top_attack)}</span>` : ""}
        <div class="bar-mini"><i style="width:${(100 * w.n_attack) / w.n_edges}%"></i></div></span>
      <span class="num muted">${int(w.n_attack)}</span></button>`).join("")
    : `<div class="empty">No windows match.</div>`;
  root.querySelectorAll("#ex-list button").forEach((b) => b.addEventListener("click", () => load(Number(b.dataset.w))));
}

async function load(wid) {
  current = wid;
  root.querySelectorAll("#ex-list button").forEach((b) => b.classList.toggle("on", Number(b.dataset.w) === wid));
  const n = $("#ex-nodes", root).value;
  const model = view.mode === "errors" ? $("#ex-model", root).value : "";
  $("#ex-title", root).innerHTML = `Window #${wid} <span class="pulse muted" style="font-size:13px">loading…</span>`;
  let g;
  try { g = await get(`/graph/${wid}?max_nodes=${n}${model ? `&model=${model}` : ""}`); }
  catch (e) { toast(e.message); return; }
  if (current !== wid) return;
  view.setData(g);
  $("#ex-title", root).textContent = `Window #${g.window_id} · task ${g.task_id + 1} (${g.task_category})`;
  $("#ex-sub", root).textContent = `${g.window_start?.slice(0, 19)} → ${g.window_end?.slice(11, 19)} · ${int(g.n_nodes)} hosts, ${int(g.n_edges)} flows` +
    (g.truncated ? ` · showing the ${n} busiest hosts (attack hosts always kept)` : "") +
    (serviceDataset ? ` · dataset served: ${serviceDataset}` : "");
  const cats = Object.entries(g.category_counts);
  $("#ex-legend", root).innerHTML = cats.map(([c, v]) =>
    `<span class="item ${view.hidden.has(c) ? "off" : ""}" data-c="${esc(c)}"><i class="line" style="background:${catColor(c)}"></i>${esc(c)} <span class="muted num">${int(v)}</span></span>`).join("")
    + `<span class="item" style="cursor:default"><i class="line" style="background:var(--critical);height:10px;width:10px;border-radius:50%"></i>host with attack flows</span>`;
  root.querySelectorAll("#ex-legend .item[data-c]").forEach((it) => it.addEventListener("click", () => {
    const c = it.dataset.c; view.hidden.has(c) ? view.hidden.delete(c) : view.hidden.add(c);
    it.classList.toggle("off"); view.draw();
  }));
  const topHosts = [...g.nodes].sort((a, b) => b.attack_degree - a.attack_degree || b.degree - a.degree).slice(0, 5);
  $("#ex-stats", root).innerHTML = `
    <div class="grid g2" style="gap:10px">
      <div><div class="muted">Attack flows</div><div style="font-size:28px;font-weight:700">${int(g.n_attack_edges)}</div><div class="muted">${pct(g.n_attack_edges / g.n_edges)} of window</div></div>
      <div><div class="muted">Hosts</div><div style="font-size:28px;font-weight:700">${int(g.n_nodes)}</div><div class="muted">${int(g.edges.length)} host pairs shown</div></div>
    </div>
    ${g.model ? `<div class="callout" style="margin-top:12px"><b style="color:var(--m-ours)">${esc(label(g.model.name))}</b> on this window:
      accuracy <b>${pct(g.model.accuracy, 2)}</b> · missed attacks <b>${int(g.model.missed_attacks)}</b> · false alarms <b>${int(g.model.false_alarms)}</b>.
      Red edges contain misclassified flows.</div>` : `<p class="note">Switch to <b>Model errors</b> to overlay a model's mistakes.</p>`}
    <h3 style="margin-top:14px;font-size:15px">Busiest attack hosts</h3>
    ${topHosts.map((h) => `<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--grid)">
      <span>Host #${h.id} <span class="muted">out ${int(h.out_degree)} · in ${int(h.in_degree)}</span></span><span class="num">${int(h.attack_degree)} attack</span></div>`).join("")}`;
}
