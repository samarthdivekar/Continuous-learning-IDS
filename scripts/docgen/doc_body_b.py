"""Sections 6-10: the interface (control by control), traces, results, operations, glossary."""
from doc_gen import S, add, build, controls_table, esc, table

# ------------------------------------------------------------------ 6.1 design system
tokens = [(n, v) for n, v in S["css_tokens"]]
palette = [(n, v) for n, v in tokens if n.startswith("--m-") or n in ("--good", "--warn", "--critical", "--accent")]
surfaces = [(n, v) for n, v in tokens if n.startswith(("--page", "--panel", "--border", "--ink", "--muted", "--grid", "--axis"))]

add(f"""
<section class="page-break">
<h2>6 &middot; The user interface</h2>
<p>The console is deliberately plain: hand-written ES modules, no framework and no build step. Two libraries are
loaded from a CDN &mdash; Chart.js for the charts and d3-force for the network layout. Every file is served as-is,
so what is in the repository is what runs in the browser.</p>

<h3>6.1 Design system</h3>
<p>Dark by default, with a light theme switched by the &#9680; button. Colours are CSS custom properties defined
once on <span class="mono">:root</span>; a model keeps the same colour on every chart of every tab, so a line can
be recognised without reading the legend.</p>

<h4>Colour roles</h4>
{table(["Token", "Value", "Used for"],
       [[f'<span class="mono">{esc(n)}</span>', f'<span class="mono">{esc(v)}</span>',
         {"--accent": "primary actions, our model's series",
          "--good": "healthy status, approved decisions",
          "--warn": "warnings, the stream pill",
          "--critical": "errors, rejected decisions, attack edges",
          "--m-ours": "GNN + EWC + replay (our model)",
          "--m-ours-topo": "the topology-augmented variant",
          "--m-gnn-naive": "GNN naive retraining",
          "--m-xgb": "XGBoost static baseline",
          "--m-ffnn": "FFNN + EWC + replay",
          "--m-ffnn-naive": "FFNN naive retraining",
          "--m-gnn-ewc": "GNN with EWC only",
          "--m-gnn-replay": "GNN with replay only",
          "--m-joint": "joint training (upper bound)"}.get(n, "chart series")]
        for n, v in palette])}

<h4>Components</h4>
{table(["Component", "Class", "What it is"],
       [["Card", '<span class="mono">.card</span>', "the panel every chart and table sits in; rounded, bordered, with an optional header row"],
        ["KPI tile", '<span class="mono">.kpi</span>', "one large number with a label above and a detail line below"],
        ["Segmented control", '<span class="mono">.seg</span>', "a row of buttons where exactly one is active (dataset, label mode, scope, sub-tabs)"],
        ["Status pill", '<span class="mono">.pill</span>', "a coloured dot and a word for API, ML, DB and stream state"],
        ["Tag", '<span class="mono">.tag</span>', "small rounded label: severity, 'dry run', a window number"],
        ["Data table", '<span class="mono">.data</span>', "compact table; numeric columns right-aligned, a highlighted row for the row that matters"],
        ["Heat cell", '<span class="mono">.heat</span>', "table cell whose background opacity encodes a value from 0 to 1"],
        ["Chart", '<span class="mono">.chart</span>', "fixed-height canvas rendered by Chart.js (line, bar, horizontal bar, logarithmic)"],
        ["Graph stage", '<span class="mono">.graph-stage</span>', "the force-directed network canvas with hover tooltip"],
        ["Banner", '<span class="mono">.banner</span>', "full-width message under the header when something is wrong"],
        ["Drawer", '<span class="mono">.drawer</span>', "the Help panel sliding in from the right with a glossary"],
        ["Tour card", '<span class="mono">.tour</span>', "the five-step guided walk, bottom right"],
        ["Toast", '<span class="mono">.toast</span>', "transient confirmation, bottom right, disappears after a few seconds"],
        ["Empty state", '<span class="mono">.empty</span>', "dashed box reading 'not run yet' or the error returned"]])}

<h4>Layout and type</h4>
<ul>
<li><b>Grid</b> &mdash; panels are laid out with CSS grid helpers (<span class="mono">.g2</span>,
<span class="mono">.g3</span>, <span class="mono">.g4</span>, <span class="mono">.g-5-7</span>,
<span class="mono">.g-7-5</span>, <span class="mono">.g-8-4</span>). Below 900&nbsp;px everything becomes one
column; below 1500&nbsp;px the header compacts so it fits a projector in one line.</li>
<li><b>Type</b> &mdash; the system UI font for text, a monospace font for anything an analyst might copy
(IP addresses, firewall rules, file paths).</li>
<li><b>Numbers</b> &mdash; shown the way a person reads them: thousands separators, percentages with sensible
precision, and never scientific notation (a port renders as 56,737, not 5.674e+04).</li>
</ul>
</section>
""")

# ------------------------------------------------------------------ 6.2 shell
add(f"""
<section class="page-break">
<h3>6.2 The shell: header, tabs, and the parts that are always there</h3>
<p>One HTML page (<span class="mono">dashboard/index.html</span>) holds the header, the tab strip and eight empty
sections. <span class="mono">js/main.js</span> routes between them: changing the URL hash loads that tab's module
on first use, so nothing is fetched for a tab nobody opens.</p>

<h4>Header controls (always visible)</h4>
{table(["Control", "Widget", "What it does"],
       [["CIC-IDS2017 / CSE-CIC-IDS2018", "segmented control", "switches dataset; every open tab re-reads its data for that dataset"],
        ["Multiclass / Binary", "segmented control", "switches between named attack types and attack-vs-benign"],
        ["API &middot; ML &middot; DB &middot; Stream", "status pills", "polled every 4 seconds from /health; green when healthy, red when not; the stream pill shows live progress"],
        ["Compare models", "checkbox", "off shows the deployed model and two reference points; on shows every baseline and ablation"],
        ["&#9654; Tour", "button", "starts the five-step guided walk"],
        ["? Help", "button", "opens the Help drawer (glossary, where to start); opens itself on a first visit"],
        ["&#9680;", "button", "toggles dark and light theme; charts are re-rendered with the new palette"]])}

<h4>Tabs</h4>
{table(["Group", "Tab", "Module", "What it answers"],
       [["Operate", t["label"].replace(" LIVE", ""), f'<span class="mono">views/{t["view"]}.js</span>', t["title"]]
        if i < 5 else
        ["Evaluate", t["label"].replace(" LIVE", ""), f'<span class="mono">views/{t["view"]}.js</span>', t["title"]]
        for i, t in enumerate(S["tabs"])])}

<h4>Keyboard</h4>
<ul>
<li><span class="mono">1</span>&ndash;<span class="mono">8</span> &mdash; switch tab</li>
<li><span class="mono">?</span> &mdash; open or close the Help drawer &nbsp;&middot;&nbsp;
    <span class="mono">Esc</span> &mdash; close it</li>
</ul>

<h4>Always-on behaviour</h4>
<ul>
<li><b>Health polling</b> &mdash; every 4 seconds; the answer is cached server-side for 3 seconds so a dead model
service cannot slow the page down.</li>
<li><b>Banner</b> &mdash; appears when the model service or the API is unreachable, naming the tabs that still
work. Dismissing it hides that message only; a different problem shows again.</li>
<li><b>API key</b> &mdash; if the server requires one, the console asks for it once and remembers it in the
browser. Downloads fetch with the key as a header, so it never appears in a URL.</li>
<li><b>Preferences</b> &mdash; theme, dataset, label mode, compare toggle, chosen model and sub-tab are
remembered per browser.</li>
</ul>
</section>
""")

# ------------------------------------------------------------------ 6.3+ per tab
TABS = [
    ("6.3", "Overview", "dashboard/js/views/overview.js", None,
     "The answer to 'does it work?' in one screen.",
     ["<b>Plain-words summary</b> &mdash; a sentence built from the result files: how many attack types were "
      "learned, how much of the first one is still detected, and how many false alarms per 100,000 flows.",
      "<b>Four KPI tiles</b> &mdash; macro-F1 with its standard deviation over seeds, retention of the first "
      "attack (with the naive model's figure for contrast), false-positive rate, and drift-triggered retrains.",
      "<b>Verdict table</b> &mdash; per model: does it adapt, does it remember, macro-F1, false-positive rate. "
      "A tick appears above 80 %, which is stated on the panel rather than left implicit.",
      "<b>Attack timeline</b> &mdash; a stacked horizontal bar chart of attack and benign flows per task.",
      "<b>Architecture diagram</b> &mdash; inline SVG of the five layers.",
      "<b>Dataset panel</b> &mdash; flow and window counts, features, task segmentation, read from the processed "
      "metadata (<span class='mono'>/results/data_summary</span>)."],
     {"": ""}),
    ("6.4", "Incident queue", "dashboard/js/views/soc.js", ["dashboard/js/views/soc.js"],
     "What an analyst actually works through: alerts grouped into incidents, each explained, each with a "
     "proposed containment action awaiting a human decision.",
     ["<b>Scope</b> &mdash; one window, or a scan of the last 10/20/50 windows ranked by severity (a shift's queue).",
      "<b>KPI row</b> &mdash; flows analysed, flagged flows, incidents, and either the share of incidents that are "
      "real (checked against ground truth, demo only) or the busiest window in the scan.",
      "<b>Incident list</b> &mdash; severity-ranked buttons with category colour, key host, size, confidence and a "
      "severity bar; filters narrow by category and severity.",
      "<b>Detail panel</b> &mdash; the plain-English explanation, a horizontal bar chart of feature attribution "
      "(red pushes towards the verdict, blue against), network context facts, the proposed action with the exact "
      "firewall rule for Linux and Windows, and the approve / reject controls.",
      "<b>Decision log</b> &mdash; every proposal and decision, filterable, with who decided and when."],
     {"soc-win": "chooses the traffic window (test windows that contain attacks, biggest first)",
      "soc-limit": "how many recent windows a scan covers",
      "soc-model": "which detector scores the window (the graph model, the per-flow model, or naive retraining)",
      "soc-th": "minimum confidence; alerts below it are dropped before grouping",
      "soc-go": "calls <span class='mono'>/incidents/{window}</span> or <span class='mono'>/incidents/scan</span> and renders the queue",
      "soc-cat": "filters the list to one attack category",
      "soc-sev": "filters by severity (critical only, or high and above)",
      "soc-csv": "downloads the visible incidents as CSV, built in the browser",
      "soc-cef": "downloads the window's incidents as CEF lines for a SIEM (<span class='mono'>/incidents/{window}/cef</span>)",
      "soc-copy": "copies the firewall rule shown above to the clipboard",
      "soc-report": "opens the printable one-page report (<span class='mono'>/incidents/{window}/report</span>)",
      "soc-approve": "records the proposed action as approved &mdash; a dry run; nothing is executed",
      "soc-reject": "records it as rejected",
      "soc-analyst": "the name stored with the decision",
      "soc-note": "an optional note stored with the decision",
      "One window": "scope switch: a single window",
      "Recent windows": "scope switch: the last N windows, ranked",
      "Linux (iptables)": "shows the iptables form of the proposed rule",
      "Windows Firewall": "shows the PowerShell form of the same rule",
      "All": "decision log filter: everything", "Pending": "decision log filter: awaiting a decision",
      "Approved": "decision log filter: approved", "Rejected": "decision log filter: rejected"}),
    ("6.5", "Live stream", "dashboard/js/views/live.js", ["dashboard/js/views/live.js"],
     "Replays the traffic stream through four models at once and shows drift detection and self-retraining "
     "as they happen.",
     ["<b>Progress and KPIs</b> &mdash; position in the stream, and per-window counts of benign, known-attack and "
      "novel/drifted predictions.",
      "<b>Live charts</b> &mdash; error rate over the stream with vertical markers where each model adapted.",
      "<b>Event feed</b> &mdash; one line per drift event: the error before and after, and whether it triggered "
      "retraining or was inside the refractory period.",
      "<b>Everything is written to the database</b> as it happens (windows, metrics, drift events), which is the "
      "same path the offline experiment uses."],
     {"lv-start": "starts the replay (<span class='mono'>POST /demo/start</span>) with the chosen speed",
      "lv-retrain": "forces an adaptation now (<span class='mono'>POST /retrain</span>), the operator override",
      "lv-stop": "stops the replay (<span class='mono'>POST /demo/stop</span>)",
      "lv-speed": "delay between windows, from fast to slow enough to narrate"}),
    ("6.6", "Graph explorer", "dashboard/js/views/explorer.js", ["dashboard/js/views/explorer.js"],
     "One window as a picture: hosts as dots, flows as lines, laid out by d3-force on a canvas.",
     ["<b>Why it exists</b> &mdash; attacks have shapes. A port scan fans out from one host; a flood fans in to one "
      "victim. That shape is exactly what the graph model can use and a per-flow model cannot.",
      "<b>Model-error overlay</b> &mdash; switches the colouring from ground truth to the chosen model's mistakes, "
      "so false alarms and missed attacks are visible as edges.",
      "<b>Interaction</b> &mdash; drag to pan, wheel to zoom, hover a node for its degree and in/out counts."],
     {"ex-task": "which task (attack period) to pick windows from",
      "ex-split": "train, validation or test windows",
      "ex-model": "which model's errors to overlay",
      "ex-nodes": "maximum hosts drawn, to keep the layout readable",
      "ex-attack": "show only edges that are attacks",
      "Ground truth": "colour edges by their true category",
      "Model errors": "colour edges by whether the model got them right"}),
    ("6.7", "Classify", "dashboard/js/views/classify.js", ["dashboard/js/views/classify.js"],
     "Run the models on demand: either a held-out window with ground truth, or your own flows.",
     ["<b>Window mode</b> &mdash; pick a test window; every loaded model classifies it and the counts are compared "
      "with the truth.",
      "<b>Your own flows</b> &mdash; upload a CSV with every CICFlowMeter feature the models were trained on. "
      "A file missing any feature in any flow is rejected with HTTP 422 naming the missing features; nothing is "
      "imputed, because a verdict computed on zero-filled features would look authoritative and mean nothing. "
      "There is no free-form paste box.",
      "<b>Output</b> &mdash; a logarithmic bar chart of predicted counts per category per model, a summary table, "
      "and for small inputs a per-flow verdict table with confidences."],
     {"cl-win": "chooses a held-out window to classify",
      "cl-run-w": "classifies that window with every loaded model (<span class='mono'>POST /predict</span>)",
      "cl-run-f": "classifies the uploaded file (parsed in the browser, then <span class='mono'>POST /predict</span>); "
                  "disabled until a file with address columns is loaded",
      "cl-file": "loads a CSV file and previews its rows and columns (5 MB limit, stated in the interface)"}),
    ("6.8", "Models", "dashboard/js/views/models.js (compare.js + general.js)",
     ["dashboard/js/views/compare.js", "dashboard/js/views/general.js"],
     "The evidence about model quality, in two sub-sections: <i>Accuracy &amp; forgetting</i> and "
     "<i>Unseen attacks &amp; IP leakage</i>.",
     ["<b>Metric over tasks</b> &mdash; any metric plotted as the task sequence progresses, with a shaded band of "
      "&plusmn;1 standard deviation across seeds.",
      "<b>Per-category recall matrix</b> &mdash; a heat table: rows are 'after task i', columns are categories, so "
      "forgetting is visible as a column going cold.",
      "<b>Forgetting (BWT)</b> &mdash; a bar chart; negative means the model lost ground on earlier tasks.",
      "<b>Confusion matrix</b> &mdash; for any model after any task.",
      "<b>Unseen attacks</b> &mdash; leave-one-attack-out detection per held-out category.",
      "<b>IP leakage</b> &mdash; the same trained model scored normally, with host identities permuted, and with "
      "sources randomised."],
     {"cmp-metric": "which metric the line chart shows",
      "cmp-rm": "which model's recall matrix is displayed",
      "cmp-cm-model": "which model's confusion matrix is displayed",
      "cmp-cm-task": "after which task the confusion matrix is taken",
      "Binary": "scores the unseen-attack test in attack-vs-benign mode",
      "Multiclass": "scores it with named categories"}),
    ("6.9", "Adaptation &amp; trust", "dashboard/js/views/adapt.js (drift.js + trust.js)",
     ["dashboard/js/views/drift.js", "dashboard/js/views/trust.js"],
     "When the system noticed traffic had changed and what it did, plus how far its decisions can be trusted. "
     "Two sub-sections: <i>Drift &amp; retraining</i> and <i>Trust</i>.",
     ["<b>Policy comparison</b> &mdash; ADWIN against a fixed schedule, an oracle that knows the true boundaries, "
      "and never adapting: retrain cost against final quality.",
      "<b>Error timeline</b> &mdash; per-window error with drift flags and adaptations marked.",
      "<b>Novelty</b> &mdash; how well each unseen attack is separated from known traffic, by three scores, plus "
      "the clustering that proposes a candidate new category.",
      "<b>Abstention</b> &mdash; false alarms before and after the model is allowed to say 'not sure'.",
      "<b>Alert load</b> &mdash; how many incidents an analyst faces at each false-alarm budget.",
      "<b>Label budget</b> &mdash; quality when only 20 or 100 flows per update are labelled, including the "
      "negative results."],
     {"dr-run": "which stream run to display",
      "tr-method": "which novelty score to chart (energy, max softmax, prototype distance)"}),
    ("6.10", "Reproducibility", "dashboard/js/views/repro.js", ["dashboard/js/views/repro.js"],
     "How every number was produced, so a reader can check rather than trust.",
     ["<b>EWC &lambda; sweep</b> &mdash; validation score against the penalty strength, on a logarithmic axis, with "
      "the selected value marked.",
      "<b>Tuning table</b> &mdash; what was chosen on the validation split, never the test split.",
      "<b>Stability ratios</b> &mdash; how sensitive the result is to the setting.",
      "<b>Run metadata</b> &mdash; git commit, seeds, device, package versions and timing for each experiment.",
      "<b>The command</b> that regenerates everything."],
     {}),
]

for num, title, path, view_file, intro, bullets, annots in TABS:
    add(f'<section class="page-break"><h3>{num} &middot; {title} <span class="mono muted">{esc(path)}</span></h3>')
    add(f"<p>{intro}</p><ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>")
    if view_file:
        add("<h4>Every control on this tab</h4>")
        add(controls_table(view_file, annots))
    add("</section>")

# ------------------------------------------------------------------ 7. traces
add("""
<section class="page-break">
<h2>7 &middot; Three journeys through the stack</h2>
<p>What actually happens between a click and a pixel.</p>

<h3>7.1 Pressing "Load incidents"</h3>
<ol>
<li><span class="mono">soc.js</span> reads the window, model and confidence slider, then calls
<span class="mono">get("/incidents/363?model=gnn_ewc_replay&amp;threshold=0")</span>.</li>
<li>The static server on 8080 proxies <span class="mono">/api/&hellip;</span> to the public API on 8000, passing the
API key header through if there is one.</li>
<li>The public API forwards to the model service on 8001 over a pooled connection.</li>
<li><span class="mono">MLService.incidents()</span> loads the cached window graph, scores it (reusing the cached
probabilities if that window and model were scored before), and reads the source/destination addresses.</li>
<li><span class="mono">build_incidents()</span> keeps flows the model called an attack, then unions hosts that share
a connection into components, one group per predicted category. Each group gets its key host, size, mean
confidence and a severity of log(size) &times; confidence.</li>
<li><span class="mono">propose_action()</span> chooses block / rate-limit / isolate from the shape of the incident
and writes the exact firewall rule.</li>
<li>The browser renders the KPI tiles, the ranked list and the detail panel, then asks
<span class="mono">/explain/363/&lt;edge&gt;</span> for the evidence behind the first incident and draws the
attribution chart.</li>
</ol>
<p class="muted">Measured: about 0.24 s per call once the window has been scored once; 3.5 s for a cold scan of
ten windows.</p>

<h3>7.2 Pressing "Start stream"</h3>
<ol>
<li><span class="mono">POST /demo/start</span> creates a <span class="mono">DemoRunner</span> thread holding four
<span class="mono">StreamRunner</span>s, one per model, warm-started from the task-1 checkpoints.</li>
<li>For each window: every model predicts first (that prediction is logged), then the labels are revealed and fed
to ADWIN as one value per flow.</li>
<li>If ADWIN reports an increase and the refractory period has passed, the model adapts on the recent windows using
its own strategy (replay + EWC for ours, plain fine-tuning for the naive baseline), and the cached scores are
invalidated.</li>
<li>Windows, metrics and drift events are written to the database as rows.</li>
<li>The browser polls <span class="mono">/stream/windows</span>, <span class="mono">/metrics</span> and
<span class="mono">/drift-status</span> and updates the charts, the feed and the stream pill.</li>
</ol>

<h3>7.3 Flicking the "Compare models" switch</h3>
<ol>
<li><span class="mono">main.js</span> stores the new value and notifies every loaded tab.</li>
<li>Each tab re-renders; <span class="mono">shownModels()</span> returns either the three story models or every
ablation (minus the topology variant, which is a documented trade-off rather than a competitor).</li>
<li>Charts redraw with the same colour per model, so a reader tracking the blue line keeps tracking it.</li>
</ol>
</section>
""")

# ------------------------------------------------------------------ 8. results
add("""
<section class="page-break">
<h2>8 &middot; Measured results</h2>
<p>Every figure here is in <span class="mono">results/</span> and visible in the console.</p>

<h3>8.1 CIC-IDS2017 &mdash; seven attack types learned in sequence, 3 seeds</h3>
<table>
<thead><tr><th>Model</th><th>Macro-F1</th><th>Retention of first attack</th><th>False-positive rate</th></tr></thead>
<tbody>
<tr><td><b>GNN + EWC + replay (ours)</b></td><td><b>0.964 &plusmn; 0.020</b></td><td>100 %</td><td>0.07 %</td></tr>
<tr><td>FFNN + EWC + replay (no graph)</td><td>0.928</td><td>100 %</td><td>0.04 %</td></tr>
<tr><td>GNN + replay only</td><td>0.948</td><td>100 %</td><td>0.12 %</td></tr>
<tr><td>GNN + EWC only</td><td>0.300</td><td>0 %</td><td>0.37 %</td></tr>
<tr><td>GNN naive retraining</td><td>0.289</td><td>0 %</td><td>0.45 %</td></tr>
<tr><td>XGBoost static</td><td>0.231</td><td>100 % (never learns anything new)</td><td>0.00 %</td></tr>
</tbody></table>

<h3>8.2 CSE-CIC-IDS2018 &mdash; 3 seeds</h3>
<table>
<thead><tr><th>Model</th><th>Macro-F1</th><th>Per seed</th></tr></thead>
<tbody>
<tr><td><b>GNN + EWC + replay (ours)</b></td><td><b>0.881 &plusmn; 0.038</b></td><td>0.855, 0.863, 0.925</td></tr>
<tr><td>FFNN + EWC + replay</td><td>0.836 &plusmn; 0.029</td><td>0.850, 0.855, 0.802</td></tr>
<tr><td>GNN naive retraining</td><td>0.298 &plusmn; 0.015</td><td>forgets completely</td></tr>
<tr><td>XGBoost static</td><td>0.282</td><td>&mdash;</td></tr>
</tbody></table>
<p class="muted">Our model leads in all three seeds, but by 0.004 and 0.009 in two of them; the average gap is
carried by the third. Stated as suggestive, not conclusive.</p>

<h3>8.3 Attacks never seen in training (2018, leave-one-attack-out)</h3>
<table>
<thead><tr><th>Held-out attack</th><th>GNN (graph)</th><th>FFNN (per-flow)</th><th>XGBoost</th></tr></thead>
<tbody>
<tr><td>BruteForce</td><td><b>99.7 %</b></td><td>0 %</td><td>0 %</td></tr>
<tr><td>DDoS</td><td><b>99.4 %</b></td><td>0 %</td><td>0 %</td></tr>
<tr><td>DoS</td><td><b>98.6 %</b></td><td>0.1 %</td><td>90.1 %</td></tr>
<tr><td>Botnet</td><td>8.5 %</td><td>0 %</td><td>0 %</td></tr>
<tr><td>Infiltration</td><td>0 %</td><td>0 %</td><td>0 %</td></tr>
</tbody></table>
<p class="muted">This is the clearest argument for the graph: structure generalises to attacks the model was never
trained on. Infiltration defeats everything, because it looks like ordinary traffic.</p>

<h3>8.4 The product layer</h3>
<table>
<thead><tr><th>Question</th><th>Measured answer</th></tr></thead>
<tbody>
<tr><td>Will analysts drown in alerts?</td><td>101,913 flow alerts &rarr; 50 incidents, 84 % of them real (2018: 105 &rarr; 90 incidents at 94 % with a budget)</td></tr>
<tr><td>Does it know when not to decide?</td><td>Abstention removes all 184 false alarms on 2017 at &alpha; = 0.05, handing 9.8 % of flows to a human</td></tr>
<tr><td>Does it spot attacks it was never taught?</td><td>Graph model 0.950 AUROC (2018, prototype score) against 0.780 for the per-flow model</td></tr>
<tr><td>Can it adapt on few labels?</td><td>1,700 labels reach 0.937 against 0.949 with everything labelled &mdash; but only with mixed sampling; uncertainty-only collapses to 0.438</td></tr>
<tr><td>Can a bad update be caught?</td><td>The safety gate rolled back one update that would have raised false alarms from 0.002 % to 0.67 %</td></tr>
</tbody></table>

<h3>8.5 Results reported as negative</h3>
<ul>
<li><b>EWC alone fails</b> (0.300, zero retention). Replay is what prevents forgetting; the combination is kept
because it is what was measured, not because EWC carries it.</li>
<li><b>A label-free drift trigger misses most changes</b> &mdash; 2 retrains instead of 16, ending at 0.338.</li>
<li><b>Uncertainty-only labelling fails</b> &mdash; a new attack the model confidently mislabels is never queried.</li>
<li><b>Topology augmentation is a trade-off</b> &mdash; robustness to randomised sources rises from 0.427 to 0.914,
but the ordinary score falls from 0.964 to 0.906 and a small class is lost in two of three seeds.</li>
<li><b>Our model is unstable on 2018 Infiltration</b> &mdash; identical runs differ by up to 0.09 macro-F1.</li>
</ul>
</section>
""")

# ------------------------------------------------------------------ 9. operations
add("""
<section class="page-break">
<h2>9 &middot; Running and operating the system</h2>

<h3>9.1 Start and stop</h3>
<pre>powershell -ExecutionPolicy Bypass -File scripts\\run_stack.ps1 -Open    # start + open the console
powershell -ExecutionPolicy Bypass -File scripts\\run_stack.ps1 -Stop     # stop everything</pre>
<table>
<thead><tr><th>Service</th><th>Port</th><th>Process</th><th>Notes</th></tr></thead>
<tbody>
<tr><td>Dashboard</td><td>8080</td><td class="mono">scripts/dashboard_server.py</td><td>serves files, proxies /api, sends security headers</td></tr>
<tr><td>Public API</td><td>8000</td><td class="mono">uvicorn src.api.app:app</td><td>results, database, forwards model calls</td></tr>
<tr><td>Model service</td><td>8001</td><td class="mono">uvicorn src.api.ml_app:app</td><td>loads four checkpoints onto the GPU</td></tr>
</tbody></table>
<p>All three bind to <span class="mono">127.0.0.1</span>, so nothing is exposed to the network by default.
Logs are written to <span class="mono">logs/stack_*.log</span>.</p>

<h3>9.2 Environment variables</h3>
{}
<h3>9.3 Reproducing the results</h3>
<pre>python -m experiments.reproduce_all --dataset cicids2017</pre>
<p>Runs data preparation, validation tuning, the EWC sweep, the task sequence over three seeds, the drift stream,
leave-one-attack-out, the IP-remap test, the figures, the report and the database seed, in that order. Add
<span class="mono">--dev</span> to any experiment for a fast partial run that writes to
<span class="mono">results/dev/</span> and is never reported.</p>

<h3>9.4 Feeding it your own traffic</h3>
<pre>python scripts\\pcap_to_flows.py capture.pcap --api http://localhost:8000</pre>
<p>Converts a capture with CICFlowMeter (installed separately), posts the flows and prints the verdicts. With an
existing flow CSV, skip the conversion with <span class="mono">--csv flows.csv</span>.</p>

<h3>9.5 Tests and continuous integration</h3>
<p>74 tests (<span class="mono">python -m pytest</span>) covering preprocessing, graph building, the learners, the
replay buffer, drift detection, the product layer, exports and all API routes, using small synthetic fixtures so
they need no dataset. GitHub Actions runs them on every push.</p>

<h3>9.6 Security posture</h3>
<ul>
<li>Checkpoints are read with PyTorch's restricted loader; the permissive one is used only as a fallback for files
inside the project's own directories.</li>
<li>Optional API key; security headers on every response; a content-security policy on the console.</li>
<li>Request bodies are size-limited and every value rendered in the browser is escaped.</li>
<li>Proposed firewall rules are never executed. Approval records a decision, nothing more.</li>
<li>Not solved on purpose, and written down as such: TLS, user accounts and roles, rate limiting, and encryption
of the stored flow records.</li>
</ul>
</section>
""".format(table(["Variable", "Effect"],
                 [['<span class="mono">GNNIDS_API_KEY</span>', "if set, every route except /health requires this key"],
                  ['<span class="mono">ML_SERVICE_URL</span>', "where the public API forwards model calls; unset means run the model in-process"],
                  ['<span class="mono">DATABASE_URL</span>', "PostgreSQL/TimescaleDB instead of the local SQLite file"],
                  ['<span class="mono">DATASET</span>, <span class="mono">LABEL_MODE</span>', "which dataset and label mode the model service serves"],
                  ['<span class="mono">CICFLOWMETER_JAR</span>', "path to CICFlowMeter for the pcap script"]])))

# ------------------------------------------------------------------ 10. glossary
add("""
<section class="page-break">
<h2>10 &middot; Glossary</h2>
<table>
<thead><tr><th style="width:150px">Term</th><th>Meaning</th></tr></thead>
<tbody>
<tr><td>Flow</td><td>One network conversation between two computers, summarised by about 50 numbers (duration, packet counts, byte rates, TCP flags).</td></tr>
<tr><td>Window</td><td>5,000 consecutive flows turned into one graph.</td></tr>
<tr><td>Task</td><td>A period in which a new attack type appears. The model learns tasks one after another.</td></tr>
<tr><td>Macro-F1</td><td>Detection quality averaged over every category, so a rare attack counts as much as a common one. 1.0 is perfect.</td></tr>
<tr><td>Retention</td><td>Share of the first attack type still detected after learning all the others. 1.0 means nothing was forgotten.</td></tr>
<tr><td>False-positive rate</td><td>Share of normal traffic wrongly flagged. Every 0.1 % is an alarm a person must dismiss.</td></tr>
<tr><td>BWT (backward transfer)</td><td>How much earlier tasks degraded after later training. Closer to zero is better; negative means forgetting.</td></tr>
<tr><td>EWC</td><td>Elastic Weight Consolidation: a penalty that protects the weights that mattered for earlier attacks.</td></tr>
<tr><td>Replay</td><td>Keeping a small sample of old traffic graphs and rehearsing them while learning something new.</td></tr>
<tr><td>ADWIN</td><td>A drift detector that watches the error rate and reports when its statistics shift.</td></tr>
<tr><td>Drift</td><td>Traffic changing over time, so a model trained on the past stops fitting the present.</td></tr>
<tr><td>Incident</td><td>A group of alerts that belong together (same attacker or same victim), reviewed as one item.</td></tr>
<tr><td>Abstention</td><td>The model declining to decide when it is not confident enough, handing the flow to a person.</td></tr>
<tr><td>Conformal prediction</td><td>A calibration method that turns scores into sets with a stated error rate per class.</td></tr>
<tr><td>Open-set detection</td><td>Spotting that something belongs to no known class &mdash; an attack type never trained on.</td></tr>
<tr><td>AUROC</td><td>How well two groups are separated by a score. 0.5 is a coin flip, 1.0 is perfect.</td></tr>
<tr><td>Dry run</td><td>A proposed action that is displayed and recorded but never executed.</td></tr>
<tr><td>CEF</td><td>Common Event Format: the line format most SIEM products ingest without a custom parser.</td></tr>
<tr><td>E-GraphSAGE</td><td>The graph neural network this model is built on, extended to carry features on edges.</td></tr>
</tbody></table>
<p class="muted" style="margin-top:18px">Documentation generated from the source tree on 5 October 2026.
Repository: github.com/samarthdivekar/Continuous-learning-IDS</p>
</section>
""")

build()
