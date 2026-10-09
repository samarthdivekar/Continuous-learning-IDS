// Drift replay: the recorded dataset's chronological stream through several models — ADWIN flags drift,
// the adaptive models retrain, the static one does not.
//
// Two modes. "Recorded run" (default) plays back the drift experiment already saved in results/ (seed 42):
// instant, and exactly the numbers the Adaptation & trust page summarises. "Recompute live" re-runs it in the
// model service — every window predicted, every drift retrained for real — which takes minutes on a laptop
// GPU and holds the model service while it runs (Live sites slows down meanwhile).
import { color, css, esc, get, HEADLINE, int, label, pct, post, state, STORY, toast } from "../lib/core.js";
import { legend, lineOptions, markerPlugin, modelDataset, mount } from "../lib/charts.js";
import { withBusy } from "../lib/ui.js";

let root, timer, playTimer, charts = {};
let mode = "recorded";
// recorded playback
let rec = null, recFor = null, pos = 0, maxPos = 0, playing = false;
// live recompute
let runId = null, lastIdx = -1, liveWindows = {};
const OURS = "gnn_ewc_replay";
const shown = () => (state.compare ? HEADLINE : STORY);
// each model's own deployment policy in the experiment: adaptive models use ADWIN, the static one never adapts
const defaultPolicy = (m) => (m === "xgboost_static" ? "never" : "adwin");

export async function mount_(el) {
  root = el;
  root.innerHTML = `
    <div class="view-head"><div><h2>Drift replay <span class="muted" style="font-size:0.5em;vertical-align:middle">(recorded dataset)</span></h2>
      <p>The recorded dataset's chronological stream (tasks 2 → last) through the models: each window is predicted first, then
      its labels feed ADWIN, and a confirmed rise in error triggers an adaptation (EWC + replay for ours). This is the training
      data, not live traffic (that is <a href="#sites">Live sites</a>).</p></div></div>
    <div class="card" style="margin-bottom:16px">
      <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center">
        <div class="seg" id="lv-mode" role="group" aria-label="replay mode">
          <button data-v="recorded" class="on" title="Play back the saved experiment run (seed 42): instant">Recorded run</button>
          <button data-v="live" title="Re-run it in the model service: minutes, and Live sites slows down meanwhile">Recompute live</button>
        </div>
        <div class="toolbar" id="lv-rec-ctl">
          <button class="btn primary" id="lv-play">▶ Play</button>
          <button class="btn" id="lv-restart">⟲ Restart</button>
          <label class="inline">Speed <select id="lv-rate" aria-label="windows per second">
            <option value="10">10 windows/s</option><option value="25" selected>25 windows/s</option><option value="100">100 windows/s</option></select></label>
        </div>
        <div class="toolbar hidden" id="lv-live-ctl">
          <label class="inline">Delay <input type="range" id="lv-speed" min="0" max="1" step="0.05" value="0.1"><span id="lv-speed-v" class="num">0.10 s/window</span></label>
          <button class="btn primary" id="lv-start">▶ Start</button>
          <button class="btn" id="lv-retrain">⟳ Retrain now</button>
          <button class="btn danger" id="lv-stop">■ Stop</button>
        </div>
      </div>
      <p class="note" id="lv-mode-note" style="margin-top:10px"></p>
      <div class="card-head" style="margin-top:6px"><div><h3 id="lv-status">Ready</h3><p class="sub" id="lv-run"></p></div>
        <div class="legend" id="lv-legend"></div></div>
      <div class="progress"><i id="lv-prog"></i></div>
      <p class="note" id="lv-progress-text"></p></div>
    <div class="grid g3">
      <div class="card"><h3>Accuracy</h3><p class="sub">tasks seen so far · dashed = adaptations</p><div class="chart"><canvas id="lv-acc"></canvas></div></div>
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

  const q = (s) => root.querySelector(s);
  q("#lv-speed").addEventListener("input", () => { q("#lv-speed-v").textContent = `${Number(q("#lv-speed").value).toFixed(2)} s/window`; });
  root.querySelectorAll("#lv-mode button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.v)));
  q("#lv-play").addEventListener("click", () => { if (playing) pause(); else play(); });
  q("#lv-restart").addEventListener("click", () => { pos = 0; play(); });
  q("#lv-start").addEventListener("click", (e) => withBusy(e.target, start));
  q("#lv-stop").addEventListener("click", (e) => withBusy(e.target, async () => {
    try { await post("/demo/stop"); toast("stopped"); await liveTick(); } catch (err) { toast(err.message); }
  }));
  q("#lv-retrain").addEventListener("click", (e) => withBusy(e.target, async () => {
    try { const r = await post("/retrain"); toast(r.accepted ? "Adaptation cycle queued" : r.reason); } catch (err) { toast(err.message); }
  }));

  const marks = () => shown().flatMap((m) => retrainPoints(m).map((x) => ({ x, color: color(m), alpha: m === OURS ? 0.6 : 0.3 })));
  const streaming = (opts) => ({
    ...opts, animation: false, parsing: false, normalized: true,
    plugins: { ...(opts.plugins || {}), decimation: { enabled: true, algorithm: "lttb", samples: 300 } },
  });
  for (const [k, id, yMax] of [["accuracy", "#lv-acc", 1], ["retention_rate", "#lv-ret", 1], ["fpr", "#lv-fpr", null]]) {
    charts[k] = mount(q(id), { type: "line", data: { datasets: [] }, plugins: [markerPlugin(marks)],
      options: streaming(lineOptions({ yMax, xTitle: "stream window" })) });
  }
  charts.err = mount(q("#lv-err"), { type: "line", data: { datasets: [] }, plugins: [markerPlugin(marks)],
    options: streaming(lineOptions({ yMax: 1, xTitle: "stream window" })) });
  // a run already going in the model service: show it; otherwise the recorded run
  let st = {};
  try { st = await get("/demo/status"); } catch { /* model service down: recorded mode still works */ }
  await setMode(st.alive ? "live" : "recorded");
}
export { mount_ as mount };
export function refresh() { if (mode === "recorded") { recFor = null; loadRecorded().then(render); } else liveTick(); }

async function setMode(m) {
  mode = m;
  pause();
  clearInterval(timer);
  root.querySelectorAll("#lv-mode button").forEach((b) => b.classList.toggle("on", b.dataset.v === m));
  root.querySelector("#lv-rec-ctl").classList.toggle("hidden", m !== "recorded");
  root.querySelector("#lv-live-ctl").classList.toggle("hidden", m !== "live");
  root.querySelector("#lv-mode-note").innerHTML = m === "recorded"
    ? "Plays back the drift experiment saved in <span class='mono'>results/</span> (seed 42): the same run the Adaptation &amp; trust page summarises."
    : "<b>Recomputes</b> the stream in the model service: every window predicted and every drift retrained for real. It takes several "
      + "minutes on a laptop GPU, and Live sites is slower while it runs.";
  if (m === "recorded") { await loadRecorded(); render(); }
  else { await liveTick(); timer = setInterval(liveTick, 2000); }
}

/* ------------------------------------------------------------------ recorded playback */
async function loadRecorded() {
  const key = state.dataset;
  if (rec && recFor === key) return;
  try { rec = await get(`/results/drift?dataset=${key}&mode=multiclass`); recFor = key; }
  catch (e) { rec = null; recFor = key; root.querySelector("#lv-status").textContent = `No recorded drift run for this dataset (${e.message}).`; return; }
  maxPos = Math.max(0, ...rec.windows.map((r) => r.stream_index));
  pos = maxPos;                                        // show the whole recorded run first; Play replays it
}

function play() {
  if (mode !== "recorded" || !rec) return;
  if (pos >= maxPos) pos = 0;
  playing = true;
  root.querySelector("#lv-play").textContent = "⏸ Pause";
  clearInterval(playTimer);
  playTimer = setInterval(() => {
    const rate = Number(root.querySelector("#lv-rate").value);
    pos = Math.min(maxPos, pos + Math.max(1, Math.round(rate / 10)));
    if (pos >= maxPos) pause();
    render();
  }, 100);
}

function pause() {
  playing = false;
  clearInterval(playTimer);
  const b = root?.querySelector("#lv-play");
  if (b) b.textContent = "▶ Play";
}

/** The recorded run up to the playback position, in the same shape the live mode builds. */
function recordedFrame() {
  const want = (r) => r.policy === defaultPolicy(r.model) && r.stream_index <= pos;
  const windows = {}, series = {};
  for (const r of rec.windows.filter(want)) (windows[r.model] ||= []).push(r);
  for (const r of rec.eval.filter(want)) (series[r.model] ||= []).push({ stream_index: r.stream_index, accuracy: r.accuracy_seen,
    retention_rate: r.retention_rate, fpr: r.fpr_seen });
  const events = rec.events.filter((e) => e.policy === defaultPolicy(e.model) && e.stream_index <= pos).slice().reverse();
  const per = {};
  for (const [m, rows] of Object.entries(windows)) {
    per[m] = { drift_flags: rows.filter((r) => r.drift_flag).length, retrains_triggered: rows.filter((r) => r.retrained).length };
  }
  return { windows, series, events, per };
}

/* ------------------------------------------------------------------ live recompute */
async function start() {
  try {
    const r = await post("/demo/start", { delay_seconds: Number(root.querySelector("#lv-speed").value), eval_every: 10 });
    runId = null; lastIdx = -1; liveWindows = {};
    toast(`Started · ${r.run_id}`);
    await liveTick();
  } catch (e) { toast(`Could not start: ${e.message}`); }
}

async function liveTick() {
  if (!root || !root.isConnected || mode !== "live") return;
  let st = {};
  try { st = await get("/demo/status"); } catch { /* ignore */ }
  const alive = !!st.alive;
  const q = (s) => root.querySelector(s);
  q("#lv-status").innerHTML = alive ? `<span class="pulse">●</span> ${esc(st.status)}` : esc(st.status || "idle");
  q("#lv-prog").style.width = st.total ? `${(100 * st.position) / st.total}%` : "0";
  q("#lv-progress-text").textContent = st.total ? `window ${int(st.position)} of ${int(st.total)} · ${esc(st.status || "")}` : "not started";
  q("#lv-start").disabled = alive; q("#lv-stop").disabled = !alive; q("#lv-retrain").disabled = !alive;
  let w;
  try { w = await get(`/stream/windows?since_index=${lastIdx}&limit=5000`); } catch { return; }
  if (w.run_id !== runId) { runId = w.run_id; liveWindows = {}; lastIdx = -1; }
  q("#lv-run").textContent = `run: ${runId || "none yet"}${st.warm_started ? " · warm-started from task-1 checkpoints" : ""}`;
  for (const r of w.windows) {
    (liveWindows[r.model_name] ||= []).push({ ...r, model: r.model_name });
    lastIdx = Math.max(lastIdx, r.stream_index);
  }
  const m = await get(`/metrics?source=stream${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`).catch(() => ({ series: {} }));
  const ds = await get(`/drift-status?limit=60${runId ? `&run_id=${encodeURIComponent(runId)}` : ""}`).catch(() => null);
  draw({ windows: liveWindows, series: m.series || {}, events: ds?.events || [], per: ds?.per_model || {} });
}

/* ------------------------------------------------------------------ drawing (both modes) */
let lastFrame = { windows: {} };
const retrainPoints = (m) => (lastFrame.windows[m] || []).filter((r) => r.retrained).map((r) => r.stream_index);

function render() {
  if (!rec) return;
  const q = (s) => root.querySelector(s);
  q("#lv-status").textContent = playing ? "Playing the recorded run" : pos >= maxPos ? "Recorded run · complete" : "Paused";
  q("#lv-run").textContent = `results/${state.dataset}/multiclass/drift · seed ${rec.seed ?? "42"} · ${int(maxPos + 1)} windows`;
  q("#lv-prog").style.width = maxPos ? `${(100 * pos) / maxPos}%` : "0";
  q("#lv-progress-text").textContent = `window ${int(pos + 1)} of ${int(maxPos + 1)}`;
  draw(recordedFrame());
}

function draw(f) {
  lastFrame = f;
  legend(root.querySelector("#lv-legend"), shown(), () => Object.values(charts));
  for (const [key, chart] of Object.entries(charts)) {
    if (key === "err") continue;
    chart.data.datasets = shown().filter((mm) => f.series[mm]).map((mm) =>
      modelDataset(mm, f.series[mm].filter((p) => p[key] != null).map((p) => ({ x: Math.max(0, p.stream_index), y: p[key] }))));
    chart.update();
  }
  const ours = f.windows[OURS] || [];
  charts.err.data.datasets = [
    { label: "true attack share", data: ours.map((r) => ({ x: r.stream_index, y: r.true_attack_fraction })), fill: true,
      borderWidth: 0, pointRadius: 0, backgroundColor: css("--grid"), stepped: true },
    ...shown().filter((mm) => f.windows[mm]).map((mm) => modelDataset(mm, f.windows[mm].map((r) => ({ x: r.stream_index, y: r.error_rate })), { pointRadius: 0 })),
    { label: "ADWIN flag (ours)", data: ours.filter((r) => r.drift_flag).map((r) => ({ x: r.stream_index, y: r.error_rate })),
      showLine: false, pointStyle: "triangle", rotation: 180, pointRadius: 8, backgroundColor: css("--ink"), borderColor: css("--ink") },
  ];
  charts.err.update();

  const lastW = ours[ours.length - 1];
  root.querySelector("#lv-counts").innerHTML = [["Benign", lastW?.pred_benign, "--good"], ["Known attack", lastW?.pred_known_attack, "--critical"],
    ["Novel / drifted", lastW?.pred_novel_drifted, "--warn"]].map(([t, v, c]) =>
    `<div class="card kpi" style="padding:12px"><div class="label">${t}</div><div class="value num" style="font-size:30px;color:var(${c})">${int(v)}</div></div>`).join("");
  root.querySelector("#lv-retrains").innerHTML = shown().map((mm) => {
    const p = f.per[mm] || { drift_flags: 0, retrains_triggered: 0 };
    return `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--grid)">
      <span><span class="swatch" style="background:${color(mm)}"></span>${esc(label(mm))}</span>
      <span class="num">${mm === "xgboost_static" ? '<span class="muted">never adapts</span>' : `${int(p.drift_flags)} flags · <b>${int(p.retrains_triggered)}</b> retrains`}</span></div>`;
  }).join("");
  root.querySelector("#lv-feed").innerHTML = f.events.length ? f.events.slice(0, 60).map((e) => `<div class="ev"><span class="num muted">w${e.stream_index ?? "–"}</span>
    <span><b style="color:${color(e.model)}">${esc(label(e.model))}</b> — error ${pct(e.prev_error)} → ${pct(e.new_error)}
    ${e.triggered_retrain ? '<span class="tag good">retrained</span>'
      : `<span class="tag warn">${esc(e.reason === "refractory" ? "refractory period" : e.reason || "logged")}</span>`}</span></div>`).join("")
    : `<div class="empty">No drift events yet.</div>`;
}
