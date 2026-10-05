"""Build the project's technical documentation as print-ready HTML (then Edge -> PDF).

Reference tables are generated from structure.json / controls.json, which were extracted
from the source itself; the prose is written around them.
"""
import json
from html import escape
from pathlib import Path

HERE = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[2]      # repository root, so this runs from any clone
S = json.loads((HERE / "structure.json").read_text(encoding="utf-8"))
CONTROLS = json.loads((HERE / "controls.json").read_text(encoding="utf-8"))
OUT_HTML = HERE / "project_documentation.html"

CSS = """
@page { size: A4; margin: 16mm 14mm 16mm 14mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.5 "Segoe UI", system-ui, sans-serif; color: #15202b; margin: 0; }
h1, h2, h3, h4 { color: #0d2235; margin: 0 0 6px; line-height: 1.25; }
h1 { font-size: 21pt; }
h2 { font-size: 15pt; margin-top: 26px; padding-bottom: 5px; border-bottom: 2px solid #2a6fb5; break-after: avoid; }
h3 { font-size: 12pt; margin-top: 18px; color: #1b4f82; break-after: avoid; }
h4 { font-size: 10.5pt; margin-top: 13px; color: #33475b; break-after: avoid; }
p { margin: 0 0 8px; }
ul, ol { margin: 0 0 9px; padding-left: 18px; }
li { margin-bottom: 3px; }
code, .mono { font-family: "Cascadia Mono", Consolas, monospace; font-size: 9pt; background: #eef2f7;
  padding: 1px 4px; border-radius: 3px; }
pre { background: #f5f8fb; border: 1px solid #dde5ee; border-left: 3px solid #2a6fb5; border-radius: 4px;
  padding: 8px 10px; font-family: "Cascadia Mono", Consolas, monospace; font-size: 8.6pt; overflow-wrap: anywhere;
  white-space: pre-wrap; margin: 0 0 10px; }
table { border-collapse: collapse; width: 100%; font-size: 8.8pt; margin: 0 0 12px; break-inside: auto; }
th { background: #e8eff7; color: #0d2235; text-align: left; font-weight: 600; }
th, td { border: 1px solid #d7e0ea; padding: 4px 6px; vertical-align: top; }
tr { break-inside: avoid; }
td.mono, th.mono { font-family: "Cascadia Mono", Consolas, monospace; font-size: 8.2pt; }
.muted { color: #5d6e80; }
.tag { display: inline-block; font-size: 7.6pt; border: 1px solid #b9c7d6; border-radius: 9px; padding: 0 6px;
  color: #33475b; background: #fff; }
.tag.get { border-color: #2f8f5b; color: #216b43; }
.tag.post { border-color: #b5742a; color: #8a5718; }
.note { background: #f3f8fd; border-left: 3px solid #2a6fb5; padding: 8px 11px; margin: 0 0 11px; font-size: 9.6pt; }
.warn { background: #fdf6ee; border-left-color: #c98a2a; }
.cover { height: 247mm; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.cover h1 { font-size: 30pt; border: 0; margin-bottom: 4px; }
.cover .sub { font-size: 13pt; color: #41586e; margin-bottom: 26px; }
.cover .meta { font-size: 10pt; color: #5d6e80; line-height: 1.9; }
.cover .rule { width: 90px; height: 3px; background: #2a6fb5; margin: 18px auto 22px; }
.page-break { break-before: page; }
.toc { font-size: 10pt; column-count: 2; column-gap: 22px; }
.toc div { margin-bottom: 3px; break-inside: avoid; }
.toc .n { color: #2a6fb5; font-weight: 600; display: inline-block; min-width: 26px; }
.toc .sub2 { padding-left: 26px; color: #41586e; font-size: 9.2pt; }
.kv { display: grid; grid-template-columns: 170px 1fr; gap: 3px 10px; font-size: 9.6pt; margin-bottom: 10px; }
.kv b { color: #33475b; font-weight: 600; }
figure { margin: 0 0 14px; }
figcaption { font-size: 8.8pt; color: #5d6e80; margin-top: 4px; }
svg { max-width: 100%; }
"""


def esc(x):
    return escape(str(x if x is not None else ""))


def table(headers, rows, classes=None):
    classes = classes or [""] * len(headers)
    head = "".join(f'<th class="{c}">{esc(h)}</th>' for h, c in zip(headers, classes))
    body = []
    for r in rows:
        cells = "".join(f'<td class="{c}">{v}</td>' for v, c in zip(r, classes))
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def module_table(prefix, title_map=None):
    """Every module under `prefix` with its classes, methods and functions."""
    out = []
    mods = [m for m in S["modules"] + S["experiments"] + S["scripts"] if m["path"].startswith(prefix)]
    for m in sorted(mods, key=lambda x: x["path"]):
        out.append(f'<h4><span class="mono">{esc(m["path"])}</span> '
                   f'<span class="muted">· {m["lines"]} lines</span></h4>')
        if m["doc"]:
            out.append(f'<p class="muted">{esc(m["doc"])}</p>')
        rows = []
        for c in m["classes"]:
            rows.append([f'<b>class {esc(c["name"])}</b>', esc(c["doc"]) or "—"])
            for meth in c["methods"]:
                rows.append([f'<span class="mono">&nbsp;&nbsp;{esc(meth["sig"])}</span>', esc(meth["doc"]) or "—"])
        for f in m["functions"]:
            rows.append([f'<span class="mono">{esc(f["sig"])}</span>', esc(f["doc"]) or "—"])
        if rows:
            out.append(table(["Definition", "Purpose"], rows, ["", ""]))
    return "\n".join(out)


def routes_table(files, prefix_filter=None):
    rows = []
    for r in S["routes"]:
        if r["file"] not in files:
            continue
        if prefix_filter and not r["path"].startswith(prefix_filter):
            continue
        tag = f'<span class="tag {r["method"].lower()}">{r["method"]}</span>'
        rows.append([tag, f'<span class="mono">{esc(r["path"])}</span>',
                     f'<span class="mono">{esc(r["handler"])}</span>', esc(r["doc"]) or "—"])
    return table(["", "Path", "Handler", "What it does"], rows, ["", "", "", ""])


def controls_table(view_file, annotations):
    rows = []
    for c in CONTROLS:
        if c["file"] != view_file:
            continue
        label = c["label"] or c["data"] or c["title"] or "—"
        if "${" in label or not label.strip():
            label = c["data"] or c["title"] or "—"
        cid = c["id"] or ""
        if "${" in cid:          # id built per row at render time (one button per incident)
            cid, note = "one per row", note if (note := annotations.get(cid, "")) else (
                "each incident in the list is a button; clicking it opens that incident in the detail panel")
        else:
            note = annotations.get(cid or label, "")
        if "${" in label:
            label = c["title"] or "list row"
        rows.append([esc(label), esc(c["type"]), f'<span class="mono">{esc(cid or "—")}</span>', note])
    return table(["Control", "Widget", "Element id", "What happens when you use it"], rows)


PARTS = []


def add(html):
    PARTS.append(html)

def build(title="GNN-IDS technical documentation"):
    html = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<title>{title}</title><style>{CSS}</style></head><body>"
            + "\n".join(PARTS) + "</body></html>")
    OUT_HTML.write_text(html, encoding="utf-8")
    print("wrote", OUT_HTML, len(html), "chars,", len(PARTS), "sections")
