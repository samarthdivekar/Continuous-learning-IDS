"""Build docs/GNN-IDS_Paper_Reference.pdf — a tech-stack + methodology reference for the research paper.

    python docs/build_paper_reference.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

OUT = Path(__file__).resolve().parent / "GNN-IDS_Paper_Reference.pdf"
INK = colors.HexColor("#15192a")
ACCENT = colors.HexColor("#5361e8")
HEAD_BG = colors.HexColor("#eef0fb")
HEAD_INK = colors.HexColor("#2a3160")
LINE = colors.HexColor("#d7dbe8")
MUTED = colors.HexColor("#555c70")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=22, leading=26, textColor=INK, spaceAfter=2)
SUB = ParagraphStyle("SUB", parent=ss["Normal"], fontSize=10.5, leading=14, textColor=MUTED, spaceAfter=12)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13.5, leading=16, textColor=HEAD_INK,
                    spaceBefore=14, spaceAfter=5, borderWidth=0, borderColor=ACCENT)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontSize=10.8, leading=13, textColor=HEAD_INK, spaceBefore=8, spaceAfter=3)
BODY = ParagraphStyle("BODY", parent=ss["Normal"], fontSize=9.6, leading=13.5, textColor=INK, spaceAfter=4, alignment=TA_LEFT)
NOTE = ParagraphStyle("NOTE", parent=BODY, fontSize=8.6, textColor=MUTED)
CELL = ParagraphStyle("CELL", parent=BODY, fontSize=8.8, leading=11.5, spaceAfter=0)
CELLK = ParagraphStyle("CELLK", parent=CELL, textColor=HEAD_INK, fontName="Helvetica-Bold")


def rule_line():
    t = Table([[""]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 1.6, ACCENT)]))
    return t


def h2(text):
    return [Spacer(1, 2), Paragraph(text, H2), rule_line(), Spacer(1, 3)]


def para(text, style=BODY):
    return Paragraph(text, style)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(i, BODY), leftIndent=10) for i in items],
                        bulletType="bullet", start="•", leftIndent=12, bulletColor=ACCENT)


def kv_table(rows, k_w=58 * mm, v_w=112 * mm):
    data = [[Paragraph(k, CELLK), Paragraph(v, CELL)] for k, v in rows]
    t = Table(data, colWidths=[k_w, v_w])
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
    return t


def head_table(header, rows, widths):
    data = [[Paragraph(c, CELLK) for c in header]] + [[Paragraph(str(c), CELL) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#c7cdf0")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5)]))
    return t


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(A4[0] / 2, 10 * mm, f"GNN-IDS research reference  ·  page {doc.page}")
    canvas.restoreState()


def build():
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=16 * mm, title="GNN-IDS Research Paper Reference")
    s = []
    s.append(Paragraph("Continual-Learning GNN Intrusion Detection System", H1))
    s.append(Paragraph("Research-paper reference — tech stack, methodology, hyper-parameters, results and "
                       "reproducibility. Author: Samarth. Every number is produced by the repository code.", SUB))

    s += h2("1. Abstract (adapt as needed)")
    s.append(para(
        "We present a network intrusion detection system that models each window of network flows as a graph "
        "(hosts as nodes, flows as edges with 83 CICFlowMeter features) and classifies edges with an "
        "<b>E-GraphSAGE</b> graph neural network. To learn new attack categories over time <b>without "
        "catastrophic forgetting</b>, we combine <b>Elastic Weight Consolidation (EWC)</b> with <b>subgraph "
        "replay</b>. On the error-corrected CIC-IDS2017 and CSE-CIC-IDS2018 datasets the graph model reaches "
        "macro-F1 0.915–0.964 while retaining 0.998–1.000 recall on the first attack after all later tasks, and "
        "detects some never-trained attacks (unseen DoS at 98.6% where a per-flow model sees &lt;0.1%). We add a "
        "product layer (incident grouping, novelty/open-set flagging, conformal abstention, calibration, dry-run "
        "response) and an online teach-and-adapt deployment path. We are explicit about limitations: the graph "
        "advantage depends on attacks coming from few hosts, and a lab-trained model does not generalise to live "
        "traffic until taught."))

    s += h2("2. Technology stack")
    s.append(Paragraph("Language &amp; machine learning", H3))
    s.append(kv_table([
        ("Language", "Python 3.12.10"), ("Deep learning", "PyTorch 2.14.0 (CUDA 12.6)"),
        ("Graph neural network", "PyTorch Geometric 2.8.0 (no compiled extensions)"),
        ("Gradient boosting", "XGBoost 3.4.1 (static baseline)"),
        ("Classic ML / metrics", "scikit-learn 1.9.1"), ("Streaming / drift", "river 0.26.1 (ADWIN)"),
        ("Numerics / data", "NumPy 2.5.3, pandas 3.0.5, SciPy 1.18.1, PyArrow 25.0.1"),
        ("Plots", "matplotlib 3.11.2")]))
    s.append(Paragraph("Backend, API &amp; data", H3))
    s.append(kv_table([
        ("Web framework", "FastAPI 0.141.1 + Uvicorn 0.53.0"),
        ("ORM / database", "SQLAlchemy 2.0 · SQLite (local) / PostgreSQL + TimescaleDB"),
        ("HTTP client", "httpx 0.28.1"), ("Config", "PyYAML 6.0.3"),
        ("Flow extraction", "CICFlowMeter (GintsEngelen fork, pinned, in Docker)"),
        ("Packet capture", "Wireshark / dumpcap + Npcap (sensor)")]))
    s.append(Paragraph("Frontend &amp; tooling", H3))
    s.append(kv_table([
        ("Dashboard", "Plain ES-module JavaScript (no framework / bundler), Chart.js, d3-force"),
        ("Desktop app", "Python tkinter (control center)"),
        ("Containers", "Docker (flow meter + isolated cyber range)"),
        ("Testing", "pytest 9.1.1 (103 tests), Playwright 1.63 (UI smoke)")]))
    s.append(Paragraph("Hardware for reported numbers: NVIDIA GeForce GTX 1650 (4 GB), 8-core CPU, 24 GB RAM, "
                       "Windows 11.", NOTE))

    s += h2("3. System architecture")
    s.append(para("Five layers, run as local processes (<font name=Courier>scripts/run_stack.ps1</font>):"))
    s.append(kv_table([
        ("Data", "SQLite (local) or PostgreSQL + TimescaleDB"),
        ("Ingestion", "data preparation + database seed (one-shot)"),
        ("ML service :8001", "models, cached graphs, live scoring, demo stream"),
        ("Public API :8000", "REST — results, predict, incidents, live traffic"),
        ("Dashboard :8080", "the web console")]))
    s.append(para("Live-traffic path: sensor (capture/replay) → CICFlowMeter (pinned, Docker) → flows → ML "
                  "service scores → console per site. Deployment is passive (SPAN port / flow exporter), dry-run only.", NOTE))

    s += h2("4. Datasets")
    s.append(head_table(
        ["Dataset", "Release", "Tasks (order)", "Flows"],
        [["CIC-IDS2017", "error-corrected (Engelen 2021)",
          "BruteForce → DoS → WebAttack → Infiltration → Botnet → PortScan → DDoS (7)", "all"],
         ["CSE-CIC-IDS2018", "error-corrected (Liu 2022)",
          "BruteForce → DoS → DDoS → WebAttack → Infiltration → Botnet (6)", "15% sample"]],
        [26 * mm, 33 * mm, 85 * mm, 26 * mm]))
    s.append(para("Both are laboratory captures with block-scheduled attacks; 83 CICFlowMeter features per flow.", NOTE))

    s += h2("5. Method &amp; model architecture")
    s.append(Paragraph("Graph construction", H3))
    s.append(bullets([
        "Flows sorted by time, cut into <b>windows of 5,000 flows</b> (never crossing a task boundary).",
        "Per window: unique IPs → nodes; each flow → a directed edge carrying its 83 scaled features.",
        "Node features: degree-based (in / out / total). IP addresses define the graph, never used as features.",
        "Scaling: signed log1p → StandardScaler (fit on task-1 train only) → clip to ±10."]))
    s.append(Paragraph("E-GraphSAGE edge classifier", H3))
    s.append(kv_table([("Hidden dimension", "64"), ("Layers", "2"), ("Dropout", "0.2"),
                       ("Edge skip", "classifier also sees the edge's own projected features"),
                       ("Parameters", "69,128 (per-flow FFNN baseline: 55,432)")]))
    s.append(Paragraph("Continual learning", H3))
    s.append(bullets([
        "<b>EWC</b> (online): protects weights important to earlier tasks; Fisher from 50 batches; λ, γ chosen on validation.",
        "<b>Subgraph replay</b>: reservoir pool of 10 windows per attack category; 2 replayed per training step (fixed budget).",
        "Loss = L(new) + replay_weight · L(replay) + EWC penalty."]))

    s += h2("6. Hyper-parameters (exact values used)")
    t1 = kv_table([("Optimizer", "Adam"), ("Learning rate", "0.001"), ("Weight decay", "0.0"),
                   ("Grad clip", "5.0"), ("Epochs (GNN / FFNN)", "10 / 10 per task"),
                   ("Class-weight power / clip", "0.5 / [0.05, 50]"), ("Seeds", "42, 43, 44 (temporal: 5)")],
                  k_w=40 * mm, v_w=42 * mm)
    t2 = kv_table([("EWC λ (selected)", "10 (val; default 100)"), ("EWC γ (selected)", "0.9 (val; default 1.0)"),
                   ("Fisher batches", "50"), ("Replay graphs / class", "10"), ("Replay graphs / step", "2"),
                   ("Window size", "5,000 flows"), ("ADWIN δ", "0.002")], k_w=40 * mm, v_w=42 * mm)
    row = Table([[t1, t2]], colWidths=[85 * mm, 85 * mm])
    row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (0, 0), 6)]))
    s.append(row)

    s += h2("7. Evaluation protocol &amp; metrics")
    s.append(bullets([
        "<b>Splits:</b> interleaved (optimistic), temporal (train on earlier traffic of each attack, test on "
        "latest), leave-one-attack-out (unseen attacks), IP-remap (permute / randomise sources).",
        "<b>Metrics:</b> macro-F1 over seen tasks, per-task recall, retention (recall on task 1 after all later "
        "tasks), backward transfer (BWT), false-positive rate, detection rate; ECE/MCE/Brier (calibration); "
        "AUROC/TPR (open-set); incident counts; serving latency / throughput.",
        "<b>Statistics:</b> paired bootstrap confidence intervals and Wilcoxon signed-rank over seeds."]))

    s += h2("8. Key results")
    s.append(head_table(
        ["Result", "Value"],
        [["Macro-F1 (2017, temporal, 5 seeds)", "0.915 ± 0.031 (95% CI 0.888–0.935)"],
         ["Macro-F1 (2017, interleaved, 3 seeds)", "0.964 ± 0.020"],
         ["Macro-F1 (2018, 3 seeds)", "0.911 ± 0.042"],
         ["Graph vs per-flow (temporal / interleaved)", "+0.044 / +0.036 macro-F1"],
         ["Retention of first attack", "0.998–1.000 (naive retraining: 0)"],
         ["Unseen DoS (leave-one-out, 2018, 3 seeds)", "98.6% (per-flow FFNN ≤ 0.07%)"],
         ["Topology dependence (random sources, 2017)", "0.952 → 0.431; FFNN unaffected"],
         ["Serving speed (GTX 1650)", "5.5 ms / 5,000-flow window (≈ 630k flows/s)"]],
        [95 * mm, 75 * mm]))

    s += h2("9. Contributions / novelty")
    s.append(ListFlowable([ListItem(Paragraph(i, BODY), leftIndent=10) for i in [
        "EWC + subgraph replay applied to <b>graph-based</b> flow IDS for class-incremental attack learning, "
        "with the three standard EWC traps handled correctly.",
        "Evidence that <b>graph structure</b> detects some never-seen attacks a per-flow model cannot.",
        "A product + deployment layer with <b>online teach-and-adapt</b> (gated against forgetting), novelty "
        "flagging, conformal abstention and dry-run response.",
        "An honest characterisation of <b>when the approach fails</b> (topology dependence; lab-to-live gap)."]],
        bulletType="1", leftIndent=14))

    s += h2("10. Related work (reviewed)")
    s.append(para("40 papers reviewed (full list in <font name=Courier>docs/GNN-IDS_Project_Guide.pdf</font> §5). "
                  "Key anchors: E-GraphSAGE (Lo et al. 2022); EWC (Kirkpatrick et al. 2017); experience replay for "
                  "continual learning; ADWIN (Bifet &amp; Gavaldà 2007); dataset-error corrections (Engelen 2021, "
                  "Liu 2022, Lanvin 2022); GNN-for-IDS survey (Bilot et al. 2023); continual learning for NIDS "
                  "(Amalapuram 2022).", NOTE))

    s += h2("11. Limitations (state these — they strengthen the paper)")
    s.append(bullets([
        "Never blocks traffic — dry-run proposals only.",
        "Graph advantage assumes attackers are few hosts; NAT / spoofing / distributed sources break it.",
        "A real modern attack (e.g. live nmap) is not detected out of the box — lab-to-live distribution gap.",
        "Drift detection needs delayed labels; unseen-attack detection is unreliable for some categories.",
        "Two lab datasets with block-scheduled attacks; not validated on production traffic."]))

    s += h2("12. Reproducibility")
    s.append(para("One command regenerates every number from the raw dataset zips:"))
    s.append(kv_table([("Command", "<font name=Courier>python -m experiments.reproduce_all --dataset cicids2017</font>"),
                       ("Provenance", "every results folder has run_info.json (seed, config, versions, GPU, command, data hash)"),
                       ("Tests", "103 automated tests; UI smoke test over all console pages")]))

    s += h2("13. How to cite the datasets")
    s.append(para("CIC-IDS2017 / CSE-CIC-IDS2018: Sharafaldin et al., ICISSP 2018. Error-corrected releases: "
                  "Engelen et al. (WTMC 2021) and Liu et al. (IEEE CNS 2022). Cite the corrected releases, since "
                  "all results use them.", NOTE))
    s.append(Spacer(1, 10))
    s.append(para("For prose, figures and the full 40-paper review, see docs/GNN-IDS_Project_Guide.pdf and "
                  "docs/GNN-IDS_Technical_Documentation.pdf.", NOTE))

    doc.build(s, onFirstPage=footer, onLaterPages=footer)
    print("wrote", OUT, f"({OUT.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    build()
