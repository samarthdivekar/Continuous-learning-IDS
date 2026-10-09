// Live Stream: replay the chronological stream through four models, watch them diverge,
// see ADWIN flag drift and trigger adaptation; manual retrain; speed control.
import { color, css, esc, get, HEADLINE, int, label, pct, post, state, STORY, toast } from "../lib/core.js";
import { legend, lineOptions, markerPlugin, modelDataset, mount } from "../lib/charts.js";
import { withBusy } from "../lib/ui.js";

let root, timer, runId = null, lastIdx = -1, windows = {}, retrains = {}, charts = {};
const OURS = "gnn_ewc_replay";
// Respect the top-bar "Compare models" toggle, like Overview and Models do: the story (3) by default,
// every streamed model when Compare is on. (Previously this view always showed all four.)
const shown = () => (state.compare ? HEADLINE : STORY);

export async function mount_(el) {
  root = el;
  root.innerHTML = `
    <div class="view-head"><div><h2>Drift replay <span class="muted" style="font-size:0.5em;vertical-align:middle">(recorded dataset demo)</span></h2>
      <p>Replays the <b>recorded dataset's</b> chronological stream (tasks 2 → last) through the models at once — this is a demo of
      the training data, not live sensor traffic (that's <b>Live sites</b>). Each window is predicted first, then its delayed
      labels feed ADWIN; a confirmed error increase triggers an adaptation cycle (EWC + replay for ours).</p></div>
      <div class="toolbar">
        <label class="inline">Speed <input type="range" id="lv-speed" min="0" max="1" step="0.05" value="0.3"><span id="lv-speed-v" class="num">0.30 s/window</span></label>
        <button class="btn primary" id="lv-start">▶ Start stream</button>
        <button class="btn" id="lv-retrain">⟳ Retrain now</button>
        <button class="btn danger" id="lv-stop">■ Stop</button>
      </div></div>
    <div class="card" style="margin-bottom:16px"><div class="card-head"><div><h3 id="lv-status">Idle</h3>
      <p class="sub" id="lv-run">run: –</p></div><div class="legend" id="lv-legend"></div></div>
      <div class="progress"><i id="lv-prog"></i></div>
      <p class="note" id="lv-progress-text">not started</p></div>
    <div class="grid g3">
      <div class="card"><h3>Accuracy</h3><p class="sub">tasks seen so far · dashed = our adaptations</p><div class="chart"><canvas id="lv-acc"></canvas></div></div>
      <div class="card"><h3>Retention</h3><p class="sub">recall on the first attack category</p><div class="chart"><canvas id="lv-ret"></canvas></div></div>
      <div class="card"><h3>False-positive rate</h3><p class="sub">benign flagged as attack</p><div class="chart"><canvas id="lv-fpr"></canvas></div></div>
    </div>
    <div class="grid g-8-4" style="margin-top:16px">
      <div class="card"><h3>Window error rate</h3><p class="sub">▼ = ADWIN drift flag (ours) · shaded = true attack share of the window</p>
        <div class="chart tall"><canvas id="lv-err"></canvas></div></div>
      <div class="grid" style="gap:16px">
        <div class="card"><h3>Current window · ours</h3><div class="grid g3" style="gap:10px;margin-top:8px" id="lv-counts"></div>
          <p class="note">Novel/drifted = prediction confidence below 0.6.</p></div>
        <div class="card"><h3>Adaptation cycles</h3><div id="lv-retrains"></div></div>
      </div>
    </div>
    <div class="card" style="margin-top:16px"><h3>Drift event feed</h3><div class="feed" id="lv-feed"></div></div>`;
  const sp = root.querySelector("#lv-speed");
  sp.addEventListener("input", () => { root.querySelector("#lv-speed-v").textContent = `${Number(sp.value).toFixed(2)} s/window`; });
  const startBtn = root.querySelector("#lv-start");
  const stopBtn = root.querySelector("#lv-stop");
  const retrainBtn = root.querySelector("#lv-retrain");
  startBtn.addEventListener("click", () => withBusy(startBtn, start));
  stopBtn.addEventListener("click", () => withBusy(stopBtn, async () => {
    try { await post("/demo/stop"); toast("stream stopped"); await tick(); } catch (e) { toast(e.message); }
  }));
  retrainBtn.addEventListener("click", () => withBusy(retrainBtn, async () => {
    try { const r = await post("/retrain"); toast(r.accepted ? "Adaptation cycle queued" : r.reason); }
    catch (e) { toast(e.message); }
  }));
  // one marker per adaptation, in that model's colour, so you can see who retrained when
  const marks = () => shown().flatMap((m) => (retrains[m] || []).map((x) => ({ x, color: color(m), alpha: m === OURS ? 0.6 : 0.3 })));
  // a 200-window stream polled every 2 s redraws a lot: decimate the points Chart.js keeps and
  // never animate, so the line extends smoothly instead of flickering
  const streaming = (opts) => ({
    ...opts, animation: false, parsing: false, normalized: true,
    plugins: { ...(opts.plugins || {}), decimation: { enabled: true, algorithm: "lttb", samples: 300 } },
  });
  for (const [k, id, yMax] of [["accuracy", "#lv-acc", 1], ["retention_rate", "#lv-ret", 1], ["fpr", "#lv-fpr", null]]) {
    charts[k] = mount(root.querySelector(id), { type: "line", data: { datasets: [] }, plugins: [markerPlugin(marks)],
      options: streaming(lineOptions({ yMax, xTitle: "stream window" })) });
  }
  charts.err = mount(root.querySelector("#lv-err"), { type: "line", data: { datasets: [] }, plugins: [markerPlugin(marks)],
    options: streaming(lineOptions({ yMax: 1, xTitle: "stream window" })) });
  legend(root.querySelector("#lv-legend"), shown(), () => Object.values(charts));
  await tick();
  timer = setInterval(tick, 2000);
}
export { mount_ as mount };
export function refresh() { tick(); }

async function start() {
  try {
    const r = await post("/demo/start", { delay_seconds: Number(root.querySelector("#lv-speed").value), eval_every: 10 });
    runId = null; lastIdx = -1; windows = {}; retrains = {};
    toast(`Stream started · ${r.run_id}`);
  } catch (e) { toast(`Could not start: ${e.message}`); }
}

async function tick() {
  if (!root || !root.isConnected) return;
  let st = {};
  try { st = await get("/demo/status"); } catch { /* ignore */ }
  const alive = !!st.alive;
  root.querySelector("#lv-status").innerHTML = alive ? `<span class="pulse">●</span> ${esc(st.status)}` : esc(st.status || "idle");
  root.querySelector("#lv-prog").style.width = st.total ? `${(100 * st.position) / st.total}%` : "0";
  root.querySelector("#lv-progress-text").textContent = st.total
    ? `window ${int(st.position)} of ${int(st.total)} · ${esc(st.status || "")}`
    : (st.status ? esc(st.status) : "not started");
  root.querySelector("#lv-start").disabled = alive;
  root.querySelector("#lv-stop").disabled = !alive;
  root.querySelector("#lv-retrain").disabled = !alive;

  legend(root.querySelector("#lv-legend"), shown(), () => Object.values(charts));
  let w;
  try { w = await get(`/stream/windows?since_index=${lastIdx}&limit=5000`); } catch { return; }
  if (w.run_id !== runId) { runId = w.run_id; windows = {}; retrains = {}; lastIdx = -1; }
  root.querySelector("#lv-run").textContent = `run: ${runId || "none yet — start a stream or seed the recorded experiment"}${st.warm_started ? " · warm-started from task-1 checkpoints" : ""}`;
  for (const r of w.windows) {
    (windows[r.model_name] ||= []).push(r);
    if (r.retrained) (retrains[r.model_name] ||= []).push(r.stream_index);
    lastIdx = Math.max(lastIdx, r.stream_index);
  }
  const m = await get(`/metrics?source=stream${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`).catch(() => ({ series: {} }));
  for (const [key, chart] of Object.entries(charts)) {
    if (key === "err") continue;
    chart.data.datasets = shown().filter((mm) => m.series[mm]).map((mm) =>
      modelDataset(mm, m.series[mm].filter((p) => p[key] != null).map((p) => ({ x: Math.max(0, p.stream_index), y: p[key] }))));
    chart.update();
  }
  const ours = windows[OURS] || [];
  charts.err.data.datasets = [
    { label: "true attack share", data: ours.map((r) => ({ x: r.stream_index, y: r.true_attack_fraction })), fill: true,
      borderWidth: 0, pointRadius: 0, backgroundColor: css("--grid"), stepped: true },
    ...shown().filter((mm) => windows[mm]).map((mm) => modelDataset(mm, windows[mm].map((r) => ({ x: r.stream_index, y: r.error_rate })), { pointRadius: 0 })),
    { label: "ADWIN flag (ours)", data: ours.filter((r) => r.drift_flag).map((r) => ({ x: r.stream_index, y: r.error_rate })),
      showLine: false, pointStyle: "triangle", rotation: 180, pointRadius: 8, backgroundColor: css("--ink"), borderColor: css("--ink") },
  ];
  charts.err.update();

  const lastW = ours[ours.length - 1];
  root.querySelector("#lv-counts").innerHTML = [["Benign", lastW?.pred_benign, "--good"], ["Known attack", lastW?.pred_known_attack, "--critical"],
    ["Novel / drifted", lastW?.pred_novel_drifted, "--warn"]].map(([t, v, c]) =>
    `<div class="card kpi" style="padding:12px"><div class="label">${t}</div><div class="value num" style="font-size:30px;color:var(${c})">${int(v)}</div></div>`).join("");

  const ds = await get(`/drift-status?limit=60${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`).catch(() => null);
  if (ds) {
    root.querySelector("#lv-retrains").innerHTML = shown().map((mm) => {
      const p = ds.per_model[mm] || { drift_flags: 0, retrains_triggered: 0 };
      return `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--grid)">
        <span><span class="swatch" style="background:${color(mm)}"></span>${esc(label(mm))}</span>
        <span class="num">${mm === "xgboost_static" ? '<span class="muted">never adapts</span>' : `${int(p.drift_flags)} flags · <b>${int(p.retrains_triggered)}</b> retrains`}</span></div>`;
    }).join("");
    root.querySelector("#lv-feed").innerHTML = ds.events.length ? ds.events.map((e) => `<div class="ev"><span class="num muted">w${e.stream_index ?? "–"}</span>
      <span><b style="color:${color(e.model)}">${esc(label(e.model))}</b> — error ${pct(e.prev_error)} → ${pct(e.new_error)}
      ${e.triggered_retrain ? '<span class="tag good">retrained</span>'
        : `<span class="tag warn">${esc(e.reason === "refractory" ? "refractory period" : e.reason || "logged")}</span>`}</span></div>`).join("")
      : `<div class="empty">No drift events yet.</div>`;
  }
}
