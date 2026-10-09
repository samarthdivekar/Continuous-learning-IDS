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
    this.selected = null;        // the clicked edge
    this.onEdge = null;          // callback(edge) when an edge is clicked
    this.userMoved = false;      // once the person zooms or pans, stop fitting automatically
    d3.select(this.canvas).call(d3.zoom().scaleExtent([0.2, 8]).on("zoom", (e) => {
      if (e.sourceEvent) this.userMoved = true;
      this.transform = e.transform; this.draw();
    }));
    this.canvas.addEventListener("mousemove", (e) => this.onMove(e));
    this.canvas.addEventListener("click", (e) => this.onClick(e));
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
    // The stage may have been hidden (0 x 0) when the layout started: move the centre to the real middle
    // and re-settle, otherwise the graph stays piled in the top-left corner.
    if (this.sim && this.W && this.H) {
      this.sim.force("center", d3.forceCenter(this.W / 2, this.H / 2));
      if (!this.userMoved) this.sim.alpha(Math.max(this.sim.alpha(), 0.3)).restart();
    }
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
      .on("tick", () => this.draw())
      .on("end", () => { if (!this.userMoved) this.fit(); });   // whole graph in view once it has settled
    this.selected = null;
    this.userMoved = false;
    this.transform = d3.zoomIdentity;
    d3.select(this.canvas).call(d3.zoom().transform, d3.zoomIdentity);
  }

  radius(n) { return 3 + 13 * Math.sqrt(n.degree / this.maxDeg); }

  edgeColor(l) {
    if (this.mode === "errors") {
      if (!l.wrong) return css("--benign-edge");
      // benign traffic called an attack vs attack traffic missed — different failures, different colours
      return l.attack_flows > 0 ? css("--warn") : css("--critical");
    }
    return l.attack_flows > 0 ? catColor(l.category) : css("--benign-edge");
  }

  /** Nearest edge to a point, in graph coordinates. */
  edgeAt(x, y, tolerance) {
    let best = null, bestD = tolerance;
    for (const l of this.links) {
      const { x: x1, y: y1 } = l.source, { x: x2, y: y2 } = l.target;
      const dx = x2 - x1, dy = y2 - y1;
      const len2 = dx * dx + dy * dy || 1;
      const t = Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / len2));
      const d = Math.hypot(x - (x1 + t * dx), y - (y1 + t * dy));
      if (d < bestD) { bestD = d; best = l; }
    }
    return best;
  }

  onClick(e) {
    if (!this.links) return;
    const rect = this.canvas.getBoundingClientRect();
    const [x, y] = this.transform.invert([e.clientX - rect.left, e.clientY - rect.top]);
    const edge = this.edgeAt(x, y, 8 / this.transform.k);
    this.selected = edge || null;
    this.draw();
    if (edge && this.onEdge) this.onEdge(edge);
  }

  /** Zoom so the whole graph fits the stage. */
  fit() {
    if (!this.nodes?.length) return;
    const xs = this.nodes.map((n) => n.x), ys = this.nodes.map((n) => n.y);
    const pad = 40;
    const w = Math.max(1, Math.max(...xs) - Math.min(...xs)), h = Math.max(1, Math.max(...ys) - Math.min(...ys));
    const k = Math.max(0.2, Math.min(8, Math.min((this.W - pad) / w, (this.H - pad) / h)));
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const t = d3.zoomIdentity.translate(this.W / 2 - k * cx, this.H / 2 - k * cy).scale(k);
    this.transform = t;
    d3.select(this.canvas).property("__zoom", t);       // keep d3's zoom state in step without a zoom event
    this.draw();
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
    if (this.selected) {                               // the edge under review, drawn over everything
      const l = this.selected;
      ctx.globalAlpha = 1;
      ctx.strokeStyle = css("--accent-2");
      ctx.lineWidth = 3 / this.transform.k;
      ctx.beginPath(); ctx.moveTo(l.source.x, l.source.y); ctx.lineTo(l.target.x, l.target.y); ctx.stroke();
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
      this.tip.innerHTML = `<b>${best.ip ? esc(best.ip) : `Host #${best.id}`}</b><br>degree ${int(best.degree)} · out ${int(best.out_degree)} · in ${int(best.in_degree)}` +
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
