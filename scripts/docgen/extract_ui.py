"""Second pass: every dashboard control with its visible label, type and wired action."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # repository root, so this runs from any clone
OUT = Path(__file__).with_name("controls.json")
FILES = sorted((ROOT / "dashboard").rglob("*.js")) + [ROOT / "dashboard/index.html"]

BUTTON = re.compile(r'<button([^>]*)>(.*?)</button>', re.S)
SELECT = re.compile(r'<select([^>]*)>')
INPUT = re.compile(r'<input([^>]*?)>')
ATTR = lambda a, s: (re.search(rf'{a}="([^"]*)"', s) or [None, ""])[1]


def clean(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\$\{[^}]*\}", "", text)
    return " ".join(text.split())[:60]


def listeners(text):
    """id -> what the click handler does (first meaningful call in the arrow body)."""
    out = {}
    for m in re.finditer(r'\$\("#([a-zA-Z0-9_-]+)"[^)]*\)\.addEventListener\("(\w+)",\s*(.{0,200})', text, re.S):
        body = " ".join(m.group(3).split())
        call = re.search(r'(load|run|decide|openApi|post|get|window\.open|downloadCsv|toast|help|tour\.\w+|setContext|'
                         r'renderList|log|show|start|stop)\s*\(', body)
        out.setdefault(m.group(1), {"event": m.group(2), "action": call.group(1) if call else body[:50]})
    for m in re.finditer(r'\$\$\("#?([a-zA-Z0-9_ ,.#-]+)"[^)]*\)\.forEach\(\([^)]*\)\s*=>\s*\w+\.addEventListener\("(\w+)"', text):
        out.setdefault(m.group(1), {"event": m.group(2), "action": "group handler"})
    return out


controls = []
for f in FILES:
    text = f.read_text(encoding="utf-8")
    rel = str(f.relative_to(ROOT)).replace("\\", "/")
    acts = listeners(text)
    for attrs, inner in BUTTON.findall(text):
        cid = ATTR("id", attrs)
        controls.append({"file": rel, "type": "button", "id": cid, "label": clean(inner),
                         "title": ATTR("title", attrs), "classes": ATTR("class", attrs),
                         "data": ATTR("data-v", attrs) or ATTR("data-view", attrs) or ATTR("data-sub", attrs),
                         "action": acts.get(cid, {}).get("action", "")})
    for attrs in SELECT.findall(text):
        cid = ATTR("id", attrs)
        controls.append({"file": rel, "type": "select", "id": cid, "label": "", "title": ATTR("title", attrs),
                         "classes": ATTR("class", attrs), "data": "", "action": acts.get(cid, {}).get("action", "")})
    for attrs in INPUT.findall(text):
        cid = ATTR("id", attrs)
        controls.append({"file": rel, "type": f"input[{ATTR('type', attrs) or 'text'}]", "id": cid,
                         "label": ATTR("placeholder", attrs), "title": ATTR("title", attrs),
                         "classes": ATTR("class", attrs), "data": "",
                         "action": acts.get(cid, {}).get("action", "")})

OUT.write_text(json.dumps(controls, indent=1), encoding="utf-8")
by_type = {}
for c in controls:
    by_type[c["type"]] = by_type.get(c["type"], 0) + 1
print(json.dumps({"total": len(controls), **by_type}, indent=1))
