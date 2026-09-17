/* Dashboard client. Polls the REST API; draws with Chart.js + a small canvas graph renderer. */
(() => {
  "use strict";
  const API = window.API_BASE || "/api";

  // Colour follows the model, never its rank (validated categorical slots, light/dark steps).
  const DARK = matchMedia("(prefers-color-scheme: dark)").matches &&
    document.documentElement.dataset.theme !== "light";
  const MODELS = {
    gnn_ewc_replay:  { label: "GNN + EWC + replay (ours)", light: "#2a78d6", dark: "#3987e5", width: 3.5 },
    gnn_naive:       { label: "GNN naive retrain",         light: "#eb6834", dark: "#d95926", width: 2.5 },
    xgboost_static:  { label: "XGBoost static",            light: "#1baf7a", dark: "#199e70", width: 2.5 },
    ffnn_ewc_replay: { label: "FFNN + EWC + replay",       light: "#eda100", dark: "#c98500", width: 2.5 },
  };
  const color = (m) => (MODELS[m] ? (DARK ? MODELS[m].dark : MODELS[m].light) : "#898781");
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const OURS = "gnn_ewc_replay";

  const $ = (id) => document.getElementById(id);
  let source = "stream";
  let lastWindowIndex = -1;
  let runId = null;
  let windowsByModel = {};
  let retrainMarks = {};   // model -> [stream_index]
  let latestWindowId = null;

  // ------------------------------------------------------------------ legend
  $("model-legend").innerHTML = Object.entries(MODELS).map(([m, s]) =>
    `<span class="legend-item"><i style="background:${color(m)}"></i>${s.label}</span>`).join("");

  // ------------------------------------------------------------------ charts
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 15;
  Chart.defaults.color = css("--muted");

  // Vertical markers for adaptation cycles of OUR model (drawn behind data).
  const retrainPlugin = {
    id: "retrainMarks",
    beforeDatasetsDraw(chart) {
      if (source !== "stream") return;
      const xs = retrainMarks[OURS] || [];
      const { ctx, chartArea: a, scales: { x } } = chart;
      ctx.save();
      ctx.strokeStyle = color(OURS);
      ctx.globalAlpha = 0.35;
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1.5;
      xs.forEach((v) => {
        const px = x.getPixelForValue(v);
        if (px < a.left || px > a.right) return;
        ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
      });
      ctx.restore();
    },
  };

  function lineChart(id, yMax, yFmt) {
    return new Chart($(id), {
      type: "line",
      data: { datasets: [] },
      plugins: [retrainPlugin],
      options: {
        animation: false, responsive: true, maintainAspectRatio: false, parsing: false,
        interaction: { mode: "nearest", axis: "x", intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${yFmt(c.parsed.y)}` } },
        },
        scales: {
          x: { type: "linear", grid: { color: css("--grid") }, border: { color: css("--axis") },
               title: { display: true, text: "stream window" }, ticks: { precision: 0 } },
          y: { min: 0, max: yMax, grid: { color: css("--grid") }, border: { display: false },
               ticks: { callback: (v) => yFmt(v) } },
        },
      },
    });
  }
  const pct = (v) => (v == null ? "–" : `${(v * 100).toFixed(v < 0.01 && v > 0 ? 2 : 1)}%`);
  const charts = {
    accuracy: lineChart("chart-accuracy", 1, pct),
    retention_rate: lineChart("chart-retention", 1, pct),
    fpr: lineChart("chart-fpr", undefined, pct),
  };
  const errorChart = new Chart($("chart-error"), {
    type: "line",
    data: { datasets: [] },
    plugins: [retrainPlugin],
    options: {
      animation: false, responsive: true, maintainAspectRatio: false, parsing: false,
      interaction: { mode: "nearest", axis: "x", intersect: false },
      plugins: { legend: { display: false },
                 tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${pct(c.parsed.y)}` } } },
      scales: {
        x: { type: "linear", grid: { color: css("--grid") }, title: { display: true, text: "stream window" } },
        y: { min: 0, max: 1, grid: { color: css("--grid") }, ticks: { callback: pct } },
      },
    },
  });

  function dataset(model, points, extra = {}) {
    const s = MODELS[model] || { label: model, width: 2 };
    return { label: s.label, data: points, borderColor: color(model), backgroundColor: color(model),
             borderWidth: s.width, pointRadius: points.length < 30 ? 4 : 0, pointHoverRadius: 6,
             tension: 0, ...extra };
  }

  // ------------------------------------------------------------------ fetch
  async function get(path) {
    const r = await fetch(`${API}${path}`);
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return r.json();
  }
  async function post(path, body) {
    const r = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || r.status);
    return j;
  }

  async function refreshMetrics() {
    const m = await get(`/metrics?source=${source}`);
    const xKey = source === "stream" ? "stream_index" : "task_id";
    Object.entries(charts).forEach(([key, chart]) => {
      chart.options.scales.x.title.text = source === "stream" ? "stream window" : "after training task (1 = first)";
      chart.data.datasets = Object.entries(m.series)
        .filter(([model]) => MODELS[model])
        .map(([model, rows]) => dataset(model, rows
          .filter((r) => r[key] != null)
          .map((r) => ({ x: source === "stream" ? Math.max(r[xKey], 0) : r[xKey] + 1, y: r[key] }))));
      chart.update();
    });
    return m;
  }

  async function refreshWindows() {
    if (source !== "stream") return;
    const w = await get(`/stream/windows?since_index=${lastWindowIndex}`);
    if (w.run_id !== runId) {
      runId = w.run_id; windowsByModel = {}; retrainMarks = {}; lastWindowIndex = -1;
      if (!w.windows.length) return;
    }
    w.windows.forEach((r) => {
      (windowsByModel[r.model_name] ||= []).push(r);
      if (r.retrained) (retrainMarks[r.model_name] ||= []).push(r.stream_index);
      lastWindowIndex = Math.max(lastWindowIndex, r.stream_index);
    });
    errorChart.data.datasets = Object.entries(windowsByModel).filter(([m]) => MODELS[m]).map(([m, rows]) =>
      dataset(m, rows.map((r) => ({ x: r.stream_index, y: r.error_rate })), { pointRadius: 0 }));
    // triangle markers where OUR model's ADWIN flagged drift
    const flags = (windowsByModel[OURS] || []).filter((r) => r.drift_flag);
    errorChart.data.datasets.push({
      label: "ADWIN drift flag (ours)", data: flags.map((r) => ({ x: r.stream_index, y: r.error_rate })),
      showLine: false, pointStyle: "triangle", rotation: 180, pointRadius: 9, pointHoverRadius: 11,
      borderColor: css("--ink"), backgroundColor: css("--ink"),
    });
    errorChart.update();

    const ours = windowsByModel[OURS];
    if (ours && ours.length) {
      const last = ours[ours.length - 1];
      $("tile-benign").textContent = last.pred_benign.toLocaleString();
      $("tile-known").textContent = last.pred_known_attack.toLocaleString();
      $("tile-novel").textContent = last.pred_novel_drifted.toLocaleString();
      if (last.window_id !== latestWindowId) {
        latestWindowId = last.window_id;
        drawGraph(last.window_id).catch(() => {});
      }
    }
  }

  async function refreshDrift() {
    const d = await get("/drift-status?limit=40");
    const tbody = $("drift-table").querySelector("tbody");
    tbody.innerHTML = d.events.map((e) => `<tr>
        <td class="num">${e.stream_index ?? "–"}</td>
        <td>${(MODELS[e.model] || { label: e.model }).label}</td>
        <td class="num">${pct(e.prev_error)}</td><td class="num">${pct(e.new_error)}</td>
        <td class="${e.triggered_retrain ? "tag-retrain" : "tag-skip"}">${e.triggered_retrain ? "retrained" : "no retrain — " + (e.reason || "")}</td>
      </tr>`).join("") || `<tr><td colspan="5" class="muted">no drift events yet</td></tr>`;
    const rt = $("retrain-table").querySelector("tbody");
    rt.innerHTML = Object.keys(MODELS).map((m) => {
      const p = d.per_model[m] || { drift_flags: 0, retrains_triggered: 0 };
      const note = m === "xgboost_static" ? " <span class='muted'>(never adapts)</span>" : "";
      return `<tr><td>${MODELS[m].label}${note}</td><td class="num">${p.drift_flags}</td><td class="num">${p.retrains_triggered}</td></tr>`;
    }).join("");
    const demo = d.demo;
    const pill = $("status-pill");
    if (demo && demo.status) {
      pill.textContent = demo.total ? `${demo.status} ${demo.position}/${demo.total}` : demo.status;
      $("btn-start").disabled = demo.alive;
      $("btn-stop").disabled = !demo.alive;
      $("btn-retrain").disabled = !demo.alive;
    } else {
      pill.textContent = "idle"; $("btn-stop").disabled = true; $("btn-retrain").disabled = true;
    }
    const shownRun = source === "stream" ? (runId || (demo && demo.run_id) || d.run_id) : "results/ (task sequence)";
    $("subtitle").textContent = `run: ${shownRun || "none"} · source: ${source === "stream" ? "stream" : "task sequence"}`;
  }

  // ------------------------------------------------------------------ graph
  async function drawGraph(windowId) {
    const g = await get(`/graph/${windowId}?max_nodes=90`);
    $("graph-meta").textContent = `— window ${g.window_id}: ${g.n_nodes.toLocaleString()} hosts, ` +
      `${g.n_edges.toLocaleString()} flows, ${g.n_attack_edges.toLocaleString()} attack` +
      (g.truncated ? " (busiest 90 hosts shown)" : "");
    const canvas = $("graph-canvas");
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    // simple force-directed layout (deterministic seed from window id)
    let seed = windowId * 9301 + 49297;
    const rand = () => ((seed = (seed * 9301 + 49297) % 233280) / 233280);
    const nodes = g.nodes.map((n) => ({ ...n, x: W / 2 + (rand() - 0.5) * W * 0.6, y: H / 2 + (rand() - 0.5) * H * 0.6, vx: 0, vy: 0 }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const edges = g.edges.filter((e) => byId.has(e.source) && byId.has(e.target));
    const k = Math.sqrt((W * H) / Math.max(nodes.length, 1)) * 0.6;
    for (let it = 0; it < 220; it++) {
      for (const a of nodes) { a.vx = 0; a.vy = 0; }
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y; const d2 = Math.max(dx * dx + dy * dy, 1);
        const f = (k * k) / d2; a.vx += dx * f; a.vy += dy * f; b.vx -= dx * f; b.vy -= dy * f;
      }
      for (const e of edges) {
        const a = byId.get(e.source), b = byId.get(e.target);
        const dx = a.x - b.x, dy = a.y - b.y; const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = d / k; a.vx -= dx * f * 0.5; a.vy -= dy * f * 0.5; b.vx += dx * f * 0.5; b.vy += dy * f * 0.5;
      }
      const t = 8 * (1 - it / 220) + 0.5;
      for (const n of nodes) {
        n.vx += (W / 2 - n.x) * 0.02; n.vy += (H / 2 - n.y) * 0.02;
        const v = Math.sqrt(n.vx * n.vx + n.vy * n.vy) || 1;
        n.x = Math.min(W - 12, Math.max(12, n.x + (n.vx / v) * Math.min(v, t)));
        n.y = Math.min(H - 12, Math.max(12, n.y + (n.vy / v) * Math.min(v, t)));
      }
    }
    ctx.clearRect(0, 0, W, H);
    const benign = css("--benign-edge"), attack = css("--critical"), node = css("--node"), surface = css("--surface");
    for (const pass of [false, true]) {          // attack edges on top
      for (const e of edges) {
        if ((e.attack_flows > 0) !== pass) continue;
        const a = byId.get(e.source), b = byId.get(e.target);
        ctx.strokeStyle = pass ? attack : benign;
        ctx.lineWidth = Math.min(1 + Math.log2(e.flows), 5) * (pass ? 1 : 0.7);
        ctx.globalAlpha = pass ? 0.9 : 0.6;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    for (const n of nodes) {
      const r = Math.min(3 + Math.sqrt(n.degree), 16);
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 2, 0, Math.PI * 2); ctx.fillStyle = surface; ctx.fill();
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = n.attack_degree > 0 ? attack : node; ctx.fill();
    }
  }

  // ------------------------------------------------------------------ controls
  $("source").addEventListener("change", (e) => {
    source = e.target.value;
    tick();
  });
  $("btn-start").addEventListener("click", async () => {
    try { await post("/demo/start", { delay_seconds: 0.3, eval_every: 10 }); runId = null; lastWindowIndex = -1; }
    catch (err) { alert(`Could not start: ${err.message}`); }
  });
  $("btn-stop").addEventListener("click", () => post("/demo/stop").catch(() => {}));
  $("btn-retrain").addEventListener("click", async () => {
    try { const r = await post("/retrain"); if (!r.accepted) alert(r.reason); }
    catch (err) { alert(err.message); }
  });

  async function tick() {
    try {
      await Promise.all([refreshMetrics(), refreshWindows(), refreshDrift()]);
    } catch (err) {
      $("subtitle").textContent = `API error: ${err.message}`;
    }
  }
  tick();
  setInterval(tick, 2000);

  window.addEventListener("resize", () => { if (latestWindowId != null) drawGraph(latestWindowId).catch(() => {}); });
})();
