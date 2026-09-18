// Chart.js helpers: consistent axes, tooltips and marks across every tab.
import { color, css, label, MODELS, pct } from "./core.js";

export function applyDefaults() {
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 14;
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--grid");
  Chart.defaults.plugins.tooltip.backgroundColor = css("--panel");
  Chart.defaults.plugins.tooltip.borderColor = css("--border-hi");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.titleColor = css("--ink");
  Chart.defaults.plugins.tooltip.bodyColor = css("--ink-2");
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
}

const registry = new Map();
export function mount(canvas, config) {
  const prev = registry.get(canvas);
  if (prev) prev.destroy();
  const c = new Chart(canvas, config);
  registry.set(canvas, c);
  return c;
}

export function modelDataset(model, points, extra = {}) {
  const spec = MODELS[model] || {};
  const ours = model === "gnn_ewc_replay";
  return {
    label: label(model), data: points, borderColor: color(model), backgroundColor: color(model),
    borderWidth: ours ? 3.5 : 2.2, borderDash: spec.dashed ? [6, 5] : [], pointRadius: points.length <= 12 ? 4 : 0,
    pointHoverRadius: 6, tension: 0.15, ...extra,
  };
}

export function lineOptions({ yMax = 1, yFmt = pct, xTitle = "", yTitle = "", xTicks } = {}) {
  return {
    animation: false, responsive: true, maintainAspectRatio: false, parsing: false,
    interaction: { mode: "nearest", axis: "x", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${yFmt(c.parsed.y)}` } },
    },
    scales: {
      x: { type: "linear", grid: { color: css("--grid") }, border: { color: css("--axis") },
           title: { display: !!xTitle, text: xTitle }, ticks: xTicks || { precision: 0 } },
      y: { min: 0, max: yMax ?? undefined, grid: { color: css("--grid") }, border: { display: false },
           title: { display: !!yTitle, text: yTitle }, ticks: { callback: (v) => yFmt(v) } },
    },
  };
}

export function barOptions({ yMax = 1, yFmt = pct, stacked = false, horizontal = false } = {}) {
  const val = horizontal ? "x" : "y";
  const cat = horizontal ? "y" : "x";
  return {
    animation: { duration: 300 }, responsive: true, maintainAspectRatio: false, indexAxis: horizontal ? "y" : "x",
    plugins: { legend: { display: false },
               tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${yFmt(c.parsed[val])}` } } },
    scales: {
      [cat]: { stacked, grid: { display: false }, border: { color: css("--axis") } },
      [val]: { stacked, min: 0, max: yMax ?? undefined, grid: { color: css("--grid") }, border: { display: false },
               ticks: { callback: (v) => yFmt(v) } },
    },
  };
}

/** Clickable HTML legend that toggles datasets on one or more charts. */
export function legend(el, models, charts) {
  el.innerHTML = models.map((m) => `<span class="item" data-m="${m}"><i class="line" style="background:${color(m)}"></i>${label(m)}</span>`).join("");
  el.querySelectorAll(".item").forEach((it) => it.addEventListener("click", () => {
    it.classList.toggle("off");
    const hidden = it.classList.contains("off");
    charts().forEach((c) => {
      c.data.datasets.forEach((ds, i) => { if (ds.label === label(it.dataset.m)) c.setDatasetVisibility(i, !hidden); });
      c.update();
    });
  }));
}

/** Vertical dashed markers at given x positions (adaptations, task boundaries). */
export function markerPlugin(getMarks) {
  return {
    id: "markers",
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea: a, scales: { x } } = chart;
      for (const m of getMarks() || []) {
        const px = x.getPixelForValue(m.x);
        if (px < a.left || px > a.right) continue;
        ctx.save();
        ctx.strokeStyle = m.color; ctx.globalAlpha = m.alpha ?? 0.45; ctx.lineWidth = m.width ?? 1.5;
        ctx.setLineDash(m.dash ?? [4, 4]);
        ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
        if (m.label) { ctx.globalAlpha = 0.9; ctx.fillStyle = m.color; ctx.font = "12px system-ui"; ctx.fillText(m.label, px + 4, a.top + 12); }
        ctx.restore();
      }
    },
  };
}
