"""Extract the project's structure for the technical documentation PDF.

Everything is read from the source: Python signatures and docstrings via ast, dashboard
controls via a light scan of each view module. Nothing is written from memory.
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]      # repository root, so this runs from any clone
OUT = Path(__file__).with_name("structure.json")


def first_line(doc):
    if not doc:
        return ""
    for line in doc.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def sig(node):
    a = node.args
    parts = [x.arg for x in a.posonlyargs + a.args]
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    parts += [x.arg for x in a.kwonlyargs]
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    return f"{node.name}({', '.join(p for p in parts if p != 'self')})"


def walk_python(rel_dirs):
    mods = []
    for d in rel_dirs:
        for f in sorted((ROOT / d).rglob("*.py")):
            if "__pycache__" in str(f) or f.name == "__init__.py" or "docgen" in f.parts:
                continue  # the documentation generator itself is not part of the system
            tree = ast.parse(f.read_text(encoding="utf-8"))
            entry = {"path": str(f.relative_to(ROOT)).replace("\\", "/"),
                     "doc": first_line(ast.get_docstring(tree)), "classes": [], "functions": [],
                     "lines": len(f.read_text(encoding="utf-8").splitlines())}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [{"sig": sig(m), "doc": first_line(ast.get_docstring(m))}
                               for m in node.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                               and not m.name.startswith("__")]
                    entry["classes"].append({"name": node.name, "doc": first_line(ast.get_docstring(node)),
                                             "methods": methods})
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    entry["functions"].append({"sig": sig(node), "doc": first_line(ast.get_docstring(node))})
            mods.append(entry)
    return mods


def routes():
    """FastAPI routes with their handler signature and docstring."""
    out = []
    for rel in ("src/api/app.py", "src/api/ml_app.py", "src/api/results.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(src)
        prefix = "/results" if rel.endswith("results.py") else ""
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                method = dec.func.attr.upper()
                if method not in {"GET", "POST", "PUT", "DELETE"}:
                    continue
                path = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else "?"
                out.append({"file": rel, "method": method, "path": prefix + path,
                            "handler": sig(node), "doc": first_line(ast.get_docstring(node))})
    return out


def dashboard():
    """Every view module with the controls it renders and the endpoints it calls."""
    views = []
    for f in sorted((ROOT / "dashboard/js").rglob("*.js")):
        text = f.read_text(encoding="utf-8")
        ids = sorted(set(re.findall(r'id="([a-zA-Z0-9_-]+)"', text)))
        controls = {
            "buttons": sorted(set(re.findall(r'<button[^>]*id="([^"]+)"', text))),
            "selects": sorted(set(re.findall(r'<select[^>]*id="([^"]+)"', text))),
            "inputs": sorted(set(re.findall(r'<input[^>]*id="([^"]+)"', text))),
            "canvases": sorted(set(re.findall(r'<canvas[^>]*id="([^"]+)"', text))),
        }
        endpoints = sorted(set(re.findall(r'(?:get|post|openApi)\(\s*`?["\']?(/[^"\'`,)\s]+)', text)))
        views.append({"path": str(f.relative_to(ROOT)).replace("\\", "/"),
                      "doc": first_line(text.split("\n\n")[0].replace("//", "").strip()),
                      "ids": ids, "controls": controls, "endpoints": endpoints,
                      "lines": len(text.splitlines())})
    return views


def tabs():
    html = (ROOT / "dashboard/index.html").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'<button class="tab[^"]*" data-view="([^"]+)" title="([^"]*)">([^<]*)', html):
        out.append({"view": m.group(1), "title": m.group(2), "label": m.group(3).strip()})
    return out


def css_tokens():
    css = (ROOT / "dashboard/css/app.css").read_text(encoding="utf-8")
    block = css[css.index(":root"):css.index("}", css.index(":root"))]
    return re.findall(r"(--[a-z0-9-]+):\s*([^;]+);", block)


data = {
    "modules": walk_python(["src"]),
    "experiments": walk_python(["experiments"]),
    "scripts": walk_python(["scripts"]),
    "routes": routes(),
    "dashboard": dashboard(),
    "tabs": tabs(),
    "css_tokens": css_tokens(),
}
OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
counts = {k: len(v) for k, v in data.items()}
counts["functions"] = sum(len(m["functions"]) for m in data["modules"] + data["experiments"] + data["scripts"])
counts["methods"] = sum(len(c["methods"]) for m in data["modules"] for c in m["classes"])
print(json.dumps(counts, indent=1))
