"""Sections 1-5 of the documentation (cover, system, data flow, backend, API)."""
from doc_gen import CONTROLS, S, add, esc, module_table, routes_table

N_FUNCS = sum(len(m["functions"]) for m in S["modules"] + S["experiments"] + S["scripts"])
N_METHODS = sum(len(c["methods"]) for m in S["modules"] for c in m["classes"])
N_BUTTONS = len([c for c in CONTROLS if c["type"] == "button"])
N_SELECTS = len([c for c in CONTROLS if c["type"] == "select"])
N_INPUTS = len([c for c in CONTROLS if c["type"].startswith("input")])

add(f"""
<section class="cover">
  <h1>Continual-Learning GNN<br>Intrusion Detection System</h1>
  <div class="rule"></div>
  <div class="sub">Complete technical documentation<br>backend, API and user interface</div>
  <div class="meta">
    Samarth Divekar<br>
    Final-year B.Tech project<br>
    github.com/samarthdivekar/Continuous-learning-IDS<br>
    Generated 5 October 2026 from the source tree
  </div>
</section>

<section class="page-break">
<h1>What this document is</h1>
<p>This is a reference for the whole system: every Python module and the functions inside it, every HTTP
endpoint, every screen of the console, and every button, dropdown and slider on those screens &mdash; with
what each one calls on the backend and what comes back.</p>
<p>The reference tables were extracted from the source code itself (Python signatures and docstrings through
the <span class="mono">ast</span> module, interface controls by scanning the dashboard files), so they match
the code exactly rather than a description of it. The explanatory text around them was written to match.</p>
<div class="kv">
  <b>Python modules</b><span>{len(S['modules'])} under <span class="mono">src/</span>, {len(S['experiments'])} experiment scripts, {len(S['scripts'])} operational scripts</span>
  <b>Functions and methods</b><span>{N_FUNCS} functions, {N_METHODS} class methods</span>
  <b>HTTP endpoints</b><span>{len(S['routes'])} routes across three applications</span>
  <b>Interface</b><span>{len(S['tabs'])} tabs, {N_BUTTONS} buttons, {N_SELECTS} dropdowns, {N_INPUTS} other inputs</span>
  <b>Tests</b><span>74 automated tests, run on every push by GitHub Actions</span>
</div>
<h2>Contents</h2>
<div class="toc">
  <div><span class="n">1</span> The system in one page</div>
  <div><span class="n">2</span> How data flows, end to end</div>
  <div><span class="n">3</span> Backend reference</div>
  <div class="sub2">3.1 Ingestion &middot; 3.2 Preprocessing &middot; 3.3 Graph building</div>
  <div class="sub2">3.4 Models &middot; 3.5 Training &middot; 3.6 Evaluation</div>
  <div class="sub2">3.7 Drift &middot; 3.8 Product layer &middot; 3.9 Explanations</div>
  <div class="sub2">3.10 Database &middot; 3.11 Utilities &middot; 3.12 Serving</div>
  <div><span class="n">4</span> Experiment scripts</div>
  <div><span class="n">5</span> API reference (all {len(S['routes'])} routes)</div>
  <div><span class="n">6</span> The user interface</div>
  <div class="sub2">6.1 Design system &middot; 6.2 The shell</div>
  <div class="sub2">6.3&ndash;6.10 Every tab, control by control</div>
  <div><span class="n">7</span> Three journeys through the stack</div>
  <div><span class="n">8</span> Measured results</div>
  <div><span class="n">9</span> Running and operating the system</div>
  <div><span class="n">10</span> Glossary</div>
</div>
</section>
""")

add("""
<section class="page-break">
<h2>1 &middot; The system in one page</h2>
<p><b>The problem.</b> An intrusion detector is trained once and then meets attacks nobody showed it. Retrain
it on a new attack and it forgets the old ones &mdash; catastrophic forgetting. Never retrain and it goes
stale. Most detectors also judge each connection on its own, so they cannot see patterns that exist only
<i>between</i> machines.</p>
<p><b>The approach.</b> Traffic is modelled as a graph: computers are nodes, connections (flows) are edges,
and the model classifies the edges. Learning is continual &mdash; the model meets one new attack type at a
time and keeps the old ones through two mechanisms working together: a penalty protecting the weights that
mattered before (EWC) and a small rehearsal buffer of old traffic (replay). A drift detector (ADWIN) decides
<i>when</i> retraining is needed, instead of retraining on a timer.</p>
<p><b>The product on top.</b> A detector that prints 100,000 alerts is unusable, so the system groups alerts
into incidents, explains each in plain language, says when it is too unsure to decide, and proposes a
containment rule that a human approves or rejects. Nothing is ever executed automatically.</p>

<h3>The five layers</h3>
<table>
<thead><tr><th>Layer</th><th>What it does</th><th>Where it lives</th><th>Technology</th></tr></thead>
<tbody>
<tr><td>Data</td><td>reads the public capture files, cleans and samples them, stores flows</td><td class="mono">src/ingestion, src/preprocessing</td><td>pandas, pyarrow</td></tr>
<tr><td>Graph + model</td><td>builds windows of 5,000 flows into graphs; classifies every edge</td><td class="mono">src/graph, src/models</td><td>PyTorch, PyTorch Geometric</td></tr>
<tr><td>Learning</td><td>continual training, replay buffer, EWC, drift detection, evaluation</td><td class="mono">src/training, src/evaluation, src/drift</td><td>PyTorch, river</td></tr>
<tr><td>Serving</td><td>two HTTP services (public API and model service) plus a database</td><td class="mono">src/api, src/db</td><td>FastAPI, SQLAlchemy, SQLite/TimescaleDB</td></tr>
<tr><td>Interface</td><td>the eight-tab console an analyst uses</td><td class="mono">dashboard/</td><td>plain ES modules, Chart.js, d3-force</td></tr>
</tbody></table>

<h3>Why two backend services</h3>
<p>The heavy model work runs in its own process (<span class="mono">src/api/ml_app.py</span>, port 8001) and
the public API (<span class="mono">src/api/app.py</span>, port 8000) forwards model calls to it. This keeps
model loading out of the request path, and lets the console stay usable when the
model service is down: the results tabs read files and keep working, and a banner says which tabs do not.</p>

<figure>
<svg viewBox="0 0 760 300" xmlns="http://www.w3.org/2000/svg" font-family="Segoe UI" font-size="11">
  <defs><marker id="ar" markerWidth="9" markerHeight="7" refX="8" refY="3.5" orient="auto">
    <polygon points="0 0, 9 3.5, 0 7" fill="#2a6fb5"/></marker></defs>
  <rect x="8" y="112" width="120" height="62" rx="7" fill="#eef4fa" stroke="#9fb9d4"/>
  <text x="68" y="137" text-anchor="middle" font-weight="600">Browser</text>
  <text x="68" y="153" text-anchor="middle" fill="#5d6e80" font-size="9.5">8 tabs, ES modules</text>
  <rect x="176" y="112" width="128" height="62" rx="7" fill="#eef4fa" stroke="#9fb9d4"/>
  <text x="240" y="132" text-anchor="middle" font-weight="600">Static server</text>
  <text x="240" y="147" text-anchor="middle" fill="#5d6e80" font-size="9.5">port 8080</text>
  <text x="240" y="161" text-anchor="middle" fill="#5d6e80" font-size="9.5">proxies /api</text>
  <rect x="352" y="112" width="128" height="62" rx="7" fill="#e4f0e8" stroke="#8fbfa3"/>
  <text x="416" y="132" text-anchor="middle" font-weight="600">Public API</text>
  <text x="416" y="147" text-anchor="middle" fill="#5d6e80" font-size="9.5">port 8000</text>
  <text x="416" y="161" text-anchor="middle" fill="#5d6e80" font-size="9.5">FastAPI</text>
  <rect x="528" y="112" width="128" height="62" rx="7" fill="#fdf2e6" stroke="#d6ad7c"/>
  <text x="592" y="132" text-anchor="middle" font-weight="600">Model service</text>
  <text x="592" y="147" text-anchor="middle" fill="#5d6e80" font-size="9.5">port 8001, GPU</text>
  <text x="592" y="161" text-anchor="middle" fill="#5d6e80" font-size="9.5">4 trained models</text>
  <rect x="352" y="222" width="128" height="52" rx="7" fill="#f0eef8" stroke="#aaa2cf"/>
  <text x="416" y="243" text-anchor="middle" font-weight="600">Database</text>
  <text x="416" y="258" text-anchor="middle" fill="#5d6e80" font-size="9.5">SQLite / Timescale</text>
  <rect x="528" y="222" width="128" height="52" rx="7" fill="#f0eef8" stroke="#aaa2cf"/>
  <text x="592" y="243" text-anchor="middle" font-weight="600">results/ files</text>
  <text x="592" y="258" text-anchor="middle" fill="#5d6e80" font-size="9.5">CSV &middot; JSON &middot; PNG</text>
  <rect x="528" y="22" width="128" height="52" rx="7" fill="#fdf2e6" stroke="#d6ad7c"/>
  <text x="592" y="43" text-anchor="middle" font-weight="600">cache/graphs</text>
  <text x="592" y="58" text-anchor="middle" fill="#5d6e80" font-size="9.5">window graphs</text>
  <line x1="128" y1="143" x2="170" y2="143" stroke="#2a6fb5" marker-end="url(#ar)"/>
  <line x1="304" y1="143" x2="346" y2="143" stroke="#2a6fb5" marker-end="url(#ar)"/>
  <line x1="480" y1="143" x2="522" y2="143" stroke="#2a6fb5" marker-end="url(#ar)"/>
  <line x1="416" y1="174" x2="416" y2="216" stroke="#2a6fb5" marker-end="url(#ar)"/>
  <line x1="480" y1="160" x2="522" y2="232" stroke="#2a6fb5" marker-end="url(#ar)"/>
  <line x1="592" y1="112" x2="592" y2="80" stroke="#2a6fb5" marker-end="url(#ar)"/>
</svg>
<figcaption>Request path. The browser talks only to port 8080, which serves the files and proxies
<span class="mono">/api</span> to the public API; model work is forwarded again to the model service. Saved
experiment results are read straight from disk, which is why those tabs survive a model outage.</figcaption>
</figure>
</section>
""")

add("""
<section class="page-break">
<h2>2 &middot; How data flows, end to end</h2>
<p>One flow record, from a public dataset to a coloured line on the screen.</p>
<table>
<thead><tr><th style="width:24px">#</th><th>Stage</th><th>What happens</th><th>Produced by</th><th>Stored as</th></tr></thead>
<tbody>
<tr><td>1</td><td>Raw capture</td><td>The error-corrected CIC-IDS2017 / CSE-CIC-IDS2018 releases are read; 2018 is streamed straight from its zip and each flow is kept with probability 0.15, decided without looking at the label.</td><td class="mono">src/ingestion/loader.py</td><td>zip in <span class="mono">data/raw</span></td></tr>
<tr><td>2</td><td>Cleaning</td><td>Column names canonicalised, impossible values dropped, "attempted" attacks relabelled benign, labels mapped onto 8 categories.</td><td class="mono">src/ingestion/columns.py, labels.py</td><td>&mdash;</td></tr>
<tr><td>3</td><td>Scaling and split</td><td>Features log-scaled then standardised using training data only; flows ordered in time and cut into tasks (one new attack type each) with train / validation / test splits.</td><td class="mono">src/preprocessing/</td><td class="mono">flows.parquet</td></tr>
<tr><td>4</td><td>Window graphs</td><td>Every 5,000 consecutive flows become one graph: hosts are nodes, flows are edges carrying ~50 features. Cached under a hash of the settings that produced them.</td><td class="mono">src/graph/window_builder.py</td><td class="mono">cache/graphs/</td></tr>
<tr><td>5</td><td>Training</td><td>Models learn the tasks in order. Ours keeps a replay buffer of old subgraphs and an EWC penalty; a checkpoint is written after every task.</td><td class="mono">src/training/learners.py</td><td class="mono">cache/checkpoints/</td></tr>
<tr><td>6</td><td>Evaluation</td><td>After each task the model is scored on every task seen so far: accuracy, macro-F1, retention, false-positive rate, forgetting.</td><td class="mono">src/evaluation/</td><td class="mono">results/&lt;dataset&gt;/&lt;mode&gt;/</td></tr>
<tr><td>7</td><td>Serving</td><td>The model service loads the final checkpoints; the public API reads result files and forwards model calls.</td><td class="mono">src/api/</td><td>HTTP JSON</td></tr>
<tr><td>8</td><td>Display</td><td>Each tab fetches what it needs and renders charts, tables or a force-directed graph.</td><td class="mono">dashboard/js/views/</td><td>the screen</td></tr>
</tbody></table>

<div class="note"><b>The rule the whole project follows:</b> every number shown anywhere is read from a file an
experiment script wrote. Nothing in the interface is typed in by hand, and when an experiment has not been run
the panel says "not run yet" rather than showing a number.</div>

<h3>What a window graph contains</h3>
<ul>
<li><b>Nodes</b> &mdash; the distinct hosts in those 5,000 flows. A node's only feature is its degree (how many
connections it has). This is deliberate: the model never receives IP addresses, so it cannot memorise them.</li>
<li><b>Edges</b> &mdash; one per flow, carrying the scaled features (duration, packet counts, byte rates, TCP
flags, &hellip;) and the training label.</li>
<li><b>Direction</b> &mdash; preserved. Incoming and outgoing neighbours are aggregated separately, which is how
the model distinguishes a scanner (many outgoing) from the victim of a flood (many incoming).</li>
</ul>
</section>
""")

SECTIONS = [
    ("3.1", "Ingestion", "src/ingestion",
     "Reads the public datasets: the two file layouts, the canonical column names, and the mapping from dozens "
     "of raw label strings onto the eight categories used throughout."),
    ("3.2", "Preprocessing", "src/preprocessing",
     "Turns raw flows into model-ready arrays: scaling fitted on training data only, the task sequence (one new "
     "attack type at a time) and the train/validation/test split."),
    ("3.3", "Graph building", "src/graph",
     "Builds and caches window graphs, samples subgraphs for training, and implements the IP-remap tests that "
     "check the model is not memorising host identities."),
    ("3.4", "Models", "src/models",
     "The networks and the two memory mechanisms: the edge-featured GraphSAGE model, the per-flow baseline, the "
     "EWC penalty and the replay buffer."),
    ("3.5", "Training", "src/training",
     "One uniform interface over every model, so the harness can treat a gradient-boosted tree and a graph "
     "network identically."),
    ("3.6", "Evaluation", "src/evaluation",
     "The task-sequence harness, the streaming simulation, the metrics, and the trust features (open-set "
     "novelty detection and conformal abstention)."),
    ("3.7", "Drift detection", "src/drift",
     "The ADWIN monitor that decides when traffic has changed enough to justify retraining."),
    ("3.8", "Product layer", "src/product",
     "What turns a classifier into something an analyst can use: incident grouping, proposed containment "
     "actions, and export for security information and event management (SIEM) tools."),
    ("3.9", "Explanations", "src/explain",
     "Why one flow was flagged: feature attribution, how much evidence came from neighbouring flows, and the "
     "structural facts, summarised into a sentence by rules (no language model involved)."),
    ("3.10", "Database", "src/db",
     "The schema shared by SQLite (default) and PostgreSQL/TimescaleDB (via DATABASE_URL), plus seeding."),
    ("3.11", "Utilities", "src/utils",
     "Configuration loading and overrides, tuned-setting selection, and safe checkpoint loading."),
    ("3.12", "Serving", "src/api",
     "The two FastAPI applications, the service layer that owns the models, the live-stream runner, the "
     "read-only results API and the printable report."),
]
add('<section class="page-break"><h2>3 &middot; Backend reference</h2>'
    '<p>Every module, class and function in <span class="mono">src/</span>, grouped by package. Signatures and '
    'one-line purposes come from the code itself.</p>')
for num, title, prefix, blurb in SECTIONS:
    add(f'<h3>{num} &middot; {esc(title)} <span class="mono muted">{esc(prefix)}</span></h3><p>{blurb}</p>')
    add(module_table(prefix))
add("</section>")

add('<section class="page-break"><h2>4 &middot; Experiment scripts</h2>'
    '<p>Each script writes files under <span class="mono">results/</span>; nothing else in the project writes a '
    'reported number. <span class="mono">reproduce_all.py</span> runs the whole chain in order.</p>')
add(module_table("experiments/"))
add("</section>")

add(f"""
<section class="page-break">
<h2>5 &middot; API reference</h2>
<p>All {len(S['routes'])} routes. The public API serves everything twice &mdash; at the root for direct use and
under <span class="mono">/api</span> for the dashboard &mdash; so a path listed as <span class="mono">/predict</span>
also answers at <span class="mono">/api/predict</span>.</p>

<h3>5.1 Public API <span class="mono muted">src/api/app.py &middot; port 8000</span></h3>
{routes_table(["src/api/app.py"])}

<h3>5.2 Results API <span class="mono muted">src/api/results.py &middot; read-only</span></h3>
<p>These never touch the model: they read the committed experiment outputs. A missing experiment returns 404 so
the interface can say "not run yet".</p>
{routes_table(["src/api/results.py"])}

<h3>5.3 Model service <span class="mono muted">src/api/ml_app.py &middot; port 8001, internal</span></h3>
<p>Not exposed to the browser; the public API forwards to it over a pooled connection.</p>
{routes_table(["src/api/ml_app.py"])}

<h3>5.4 Conventions</h3>
<ul>
<li><b>Errors</b> &mdash; 404 for a window, model or experiment that does not exist; 422 for a value outside its
allowed range; 409 when an action was already decided or the incident changed since it was displayed; 503 when
the model service is unreachable or its libraries cannot load.</li>
<li><b>Authentication</b> &mdash; optional. Set <span class="mono">GNNIDS_API_KEY</span> and every route except
<span class="mono">/health</span> requires an <span class="mono">X-API-Key</span> header.</li>
<li><b>Compression</b> &mdash; responses above 1 KB are gzipped; the largest (the 2018 drift stream) drops from
2,271 KB to 99 KB.</li>
<li><b>Caching</b> &mdash; model scores are cached per window, model and model version, so a repeat request for
the same window is roughly four times faster.</li>
<li><b>Safety</b> &mdash; proposed containment actions are recorded, never executed, whether approved or not.</li>
</ul>
</section>
""")
