// Interactive window-graph renderer: d3-force layout, canvas drawing, zoom/pan,
// hover tooltips, category colours and an optional "model got it wrong" overlay.
import { catColor, css, esc, int } from "./core.js";

export class GraphView {
  constructor(stage) {
    this.stage = stage;
    this.canvas = document.createElement("canvas");
    this.tip = document.createElement("div");
    this.tip.className = "graph-tip hidden";
    stage.append(this.canvas, this.tip);
    this.transform = d3.zoomIdentity;
    this.mode = "truth";      // truth | errors
    this.hidden = new Set();  // categories hidden by the filter
    this.sim = null;
    this.hover = null;
    d3.select(this.canvas).call(d3.zoom().scaleExtent([0.2, 8]).on("zoom", (e) => { this.transform = e.transform; this.draw(); }));
    this.canvas.addEventListener("mousemove", (e) => this.onMove(e));
    this.canvas.addEventListener("mouseleave", () => { this.hover = null; this.tip.classList.add("hidden"); this.draw(); });
    new ResizeObserver(() => this.resize()).observe(stage);
    this.resize();
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    this.W = this.stage.clientWidth; this.H = this.stage.clientHeight;
    this.canvas.width = this.W * dpr; this.canvas.height = this.H * dpr;
    this.ctx = this.canvas.getContext("2d");
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.draw();
  }

  setData(g) {
    this.g = g;
    const nodes = g.nodes.map((n) => ({ ...n }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links = g.edges.filter((e) => byId.has(e.source) && byId.has(e.target)).map((e) => ({ ...e }));
    this.nodes = nodes; this.links = links;
    this.maxDeg = Math.max(1, ...nodes.map((n) => n.degree));
    if (this.sim) this.sim.stop();
    this.sim = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id).distance((l) => 30 + 40 / Math.sqrt(l.flows)).strength(0.4))
      .force("charge", d3.forceManyBody().strength(-60))
      .force("center", d3.forceCenter(this.W / 2, this.H / 2))
      .force("collide", d3.forceCollide().radius((d) => this.radius(d) + 2))
      .alpha(1).alphaDecay(0.035)
      .on("tick", () => this.draw());
    this.transform = d3.zoomIdentity;
    d3.select(this.canvas).call(d3.zoom().transform, d3.zoomIdentity);
  }

  radius(n) { return 3 + 13 * Math.sqrt(n.degree / this.maxDeg); }

  edgeColor(l) {
    if (this.mode === "errors") return l.wrong > 0 ? css("--critical") : css("--benign-edge");
    return l.attack_flows > 0 ? catColor(l.category) : css("--benign-edge");
  }

  draw() {
    const { ctx, W, H } = this;
    if (!ctx) return;
    ctx.clearRect(0, 0, W, H);
    if (!this.nodes) return;
    ctx.save();
    ctx.translate(this.transform.x, this.transform.y);
    ctx.scale(this.transform.k, this.transform.k);
    for (const pass of [0, 1]) {                       // benign/correct first, highlighted on top
      for (const l of this.links) {
        const hi = this.mode === "errors" ? l.wrong > 0 : l.attack_flows > 0;
        if ((pass === 1) !== hi) continue;
        if (this.hidden.has(l.attack_flows > 0 ? l.category : "Benign")) continue;
        const focus = this.hover && (l.source === this.hover || l.target === this.hover);
        ctx.strokeStyle = this.edgeColor(l);
        ctx.globalAlpha = this.hover ? (focus ? 1 : 0.12) : (hi ? 0.9 : 0.5);
        ctx.lineWidth = Math.min(1 + Math.log2(l.flows), 6) / this.transform.k * (hi ? 1.2 : 0.8);
        ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
    for (const n of this.nodes) {
      const r = this.radius(n);
      ctx.beginPath(); ctx.arc(n.x, n.y, r + 1.5 / this.transform.k, 0, 2 * Math.PI);
      ctx.fillStyle = css("--panel-2"); ctx.fill();
      ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = n.attack_degree > 0 ? css("--critical") : css("--node");
      ctx.globalAlpha = this.hover && this.hover !== n ? 0.45 : 1;
      ctx.fill();
      if (this.hover === n) { ctx.lineWidth = 2 / this.transform.k; ctx.strokeStyle = css("--ink"); ctx.stroke(); }
    }
    ctx.restore();
  }

  onMove(e) {
    if (!this.nodes) return;
    const rect = this.canvas.getBoundingClientRect();
    const [x, y] = this.transform.invert([e.clientX - rect.left, e.clientY - rect.top]);
    let best = null, bestD = 16 / this.transform.k;
    for (const n of this.nodes) {
      const d = Math.hypot(n.x - x, n.y - y) - this.radius(n);
      if (d < bestD) { bestD = d; best = n; }
    }
    this.hover = best;
    if (best) {
      const edges = this.links.filter((l) => l.source === best || l.target === best);
      const cats = {};
      edges.forEach((l) => { if (l.attack_flows) cats[l.category] = (cats[l.category] || 0) + l.attack_flows; });
      const wrong = edges.reduce((s, l) => s + (l.wrong || 0), 0);
      this.tip.innerHTML = `<b>Host #${best.id}</b><br>degree ${int(best.degree)} · out ${int(best.out_degree)} · in ${int(best.in_degree)}` +
        `<br>attack flows ${int(best.attack_degree)}` +
        (Object.keys(cats).length ? `<br>${Object.entries(cats).map(([c, v]) => `${esc(c)}: ${int(v)}`).join(" · ")}` : "") +
        (this.mode === "errors" ? `<br>misclassified flows on shown edges: <b>${int(wrong)}</b>` : "");
      this.tip.style.left = `${Math.min(e.clientX - rect.left + 14, this.W - 290)}px`;
      this.tip.style.top = `${e.clientY - rect.top + 14}px`;
      this.tip.classList.remove("hidden");
    } else {
      this.tip.classList.add("hidden");
    }
    this.draw();
  }
}
