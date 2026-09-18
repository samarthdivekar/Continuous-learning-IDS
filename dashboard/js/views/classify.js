// Classify: run every loaded model on a cached window or on pasted flows; compare verdicts.
import { $, catColor, color, esc, get, HEADLINE, int, label, pct, post, toast } from "../lib/core.js";
import { mount } from "../lib/charts.js";

let root, catalog = [];
const SAMPLE = [
  "src_ip,dst_ip,Flow Duration,Total Fwd Packet,Total Bwd packets,Dst Port,Protocol,Flow Bytes/s,SYN Flag Count",
  "205.174.165.73,192.168.10.50,120,1,1,22,6,0,1",
  "205.174.165.73,192.168.10.50,95,1,1,23,6,0,1",
  "205.174.165.73,192.168.10.50,101,1,1,80,6,0,1",
  "192.168.10.9,172.217.10.46,560231,12,10,443,6,8923.4,1",
].join("\n");

export async function mount_(el) {
  root = el;
  root.innerHTML = `
    <div class="view-head"><div><h2>Classify traffic</h2>
      <p>Send flows through the ML service and compare every model's verdict side by side. Pick a real held-out window
      (ground truth shown), or paste your own CICFlowMeter-style rows.</p></div></div>
    <div class="grid g2">
      <div class="card"><h3>1 · A held-out window</h3><p class="sub">test-split windows only · ground truth is compared automatically</p>
        <div class="toolbar"><select id="cl-win" style="min-width:320px"></select><button class="btn primary" id="cl-run-w">Classify window</button></div></div>
      <div class="card"><h3>2 · Your own flows</h3><p class="sub">CSV with src_ip, dst_ip and any CICFlowMeter columns (original or snake_case names). Missing features are imputed as 0 and reported.</p>
        <textarea id="cl-csv">${SAMPLE}</textarea>
        <div class="toolbar" style="margin-top:8px"><button class="btn primary" id="cl-run-f">Classify flows</button>
          <label class="btn" style="cursor:pointer">Load CSV file<input type="file" id="cl-file" accept=".csv,text/csv" hidden></label></div></div>
    </div>
    <div class="card" style="margin-top:16px"><h3>Verdicts</h3><div id="cl-out"><div class="empty">Run a classification above.</div></div></div>`;
  try { catalog = (await get("/windows/catalog")).filter((w) => w.split === "test"); } catch { catalog = []; }
  const firstAttack = catalog.find((w) => w.n_attack > 200);
  $("#cl-win", root).innerHTML = catalog.map((w) => `<option value="${w.window_id}" ${firstAttack && w.window_id === firstAttack.window_id ? "selected" : ""}>#${w.window_id} · task ${w.task_id + 1} ${esc(w.task_category)} · ${int(w.n_attack)} attack flows</option>`).join("");
  $("#cl-run-w", root).addEventListener("click", () => run({ window_id: Number($("#cl-win", root).value) }));
  $("#cl-run-f", root).addEventListener("click", () => {
    try { run({ flows: parseCsv($("#cl-csv", root).value), store: false }); } catch (e) { toast(e.message); }
  });
  $("#cl-file", root).addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    if (f.size > 5e6) { toast("File too large for the browser demo (max 5 MB)"); return; }
    $("#cl-csv", root).value = await f.text();
  });
}
export { mount_ as mount };

function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("Need a header row and at least one flow");
  const head = lines[0].split(",").map((s) => s.trim());
  const si = head.findIndex((h) => /^(src[_ ]?ip|source ip)$/i.test(h)), di = head.findIndex((h) => /^(dst[_ ]?ip|destination ip)$/i.test(h));
  if (si < 0 || di < 0) throw new Error("CSV needs src_ip and dst_ip columns");
  if (lines.length > 5001) throw new Error("Max 5,000 flows per request in the browser demo");
  return lines.slice(1).map((l, k) => {
    const v = l.split(",");
    const features = {};
    head.forEach((h, i) => { if (i !== si && i !== di && !/label|timestamp|flow id/i.test(h) && v[i] !== undefined && v[i] !== "" && !Number.isNaN(Number(v[i]))) features[h] = Number(v[i]); });
    return { ts: new Date(Date.UTC(2017, 6, 4, 12, 0, k % 60)).toISOString(), src_ip: v[si].trim(), dst_ip: v[di].trim(), features };
  });
}

async function run(body) {
  const out = $("#cl-out", root);
  out.innerHTML = `<div class="empty pulse">Classifying…</div>`;
  let r;
  try { r = await post("/predict", body); } catch (e) { out.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
  const models = HEADLINE.filter((m) => r.models[m]);
  const allLabels = [...new Set([...Object.keys(r.true_counts || {}), ...models.flatMap((m) => Object.keys(r.models[m].counts))])];
  out.innerHTML = `
    <p class="sub">${int(r.n_flows)} flows between ${int(r.n_nodes)} hosts${r.warnings?.length ? ` · <span class="tag warn">${esc(r.warnings[0])}</span>` : ""}
      ${Object.keys(r.unavailable || {}).length ? ` · unavailable: ${esc(Object.keys(r.unavailable).join(", "))}` : ""}</p>
    <div class="grid g2"><div class="chart"><canvas id="cl-chart"></canvas></div><div id="cl-table"></div></div>
    ${r.n_flows <= 50 ? `<h3 style="margin-top:14px;font-size:15px">Per-flow verdicts</h3><div class="table-wrap"><table class="data"><thead><tr><th>#</th>${models.map((m) => `<th>${esc(label(m))}</th>`).join("")}</tr></thead>
      <tbody>${r.models[models[0]].labels.map((_, i) => `<tr><td class="num">${i + 1}</td>${models.map((m) => {
        const l = r.models[m].labels[i]; return `<td><span class="swatch" style="background:${catColor(l)}"></span>${esc(l)} <span class="muted num">${pct(r.models[m].confidence[i], 0)}</span></td>`; }).join("")}</tr>`).join("")}</tbody></table></div>` : ""}`;
  const sets = models.map((m) => ({ label: label(m), data: allLabels.map((l) => r.models[m].counts[l] || 0), backgroundColor: color(m), borderRadius: 5 }));
  if (r.true_counts) sets.unshift({ label: "ground truth", data: allLabels.map((l) => r.true_counts[l] || 0), backgroundColor: getComputedStyle(document.documentElement).getPropertyValue("--ink-2"), borderRadius: 5 });
  mount($("#cl-chart", root), { type: "bar", data: { labels: allLabels, datasets: sets },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: true, position: "bottom" } },
      scales: { x: { grid: { display: false } }, y: { type: "logarithmic", title: { display: true, text: "flows (log scale)" } } } } });
  const acc = (m) => {
    if (!r.true_counts) return "–";
    const correct = allLabels.reduce((s, l) => s + Math.min(r.true_counts[l] || 0, r.models[m].counts[l] || 0), 0);
    return pct(correct / r.n_flows, 2) + '<span class="muted"> (count agreement)</span>';
  };
  $("#cl-table", root).innerHTML = `<div class="table-wrap"><table class="data"><thead><tr><th>Model</th><th>Flagged as attack</th><th>Agreement with truth</th></tr></thead><tbody>
    ${models.map((m) => { const benign = r.models[m].counts.Benign || 0; return `<tr><td><span class="swatch" style="background:${color(m)}"></span>${esc(label(m))}</td>
      <td class="num">${int(r.n_flows - benign)}</td><td class="num">${acc(m)}</td></tr>`; }).join("")}</tbody></table></div>
    ${r.true_counts ? `<p class="note">Agreement compares per-class counts (an upper bound on accuracy). Use Graph Explorer → Model errors for exact per-flow mistakes.</p>` : ""}`;
}
