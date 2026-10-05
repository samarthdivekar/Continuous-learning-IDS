# Documentation generator

Rebuilds `GNN-IDS_Technical_Documentation.pdf` from the source tree, so the reference
tables never drift away from the code.

```bash
python scripts/docgen/extract_api.py     # Python signatures + routes -> structure.json
python scripts/docgen/extract_ui.py      # dashboard controls -> controls.json
python scripts/docgen/make_doc.py        # -> project_documentation.html
```

Then print the HTML to PDF with a Chromium browser:

```bash
msedge --headless=new --no-pdf-header-footer --print-to-pdf=GNN-IDS_Technical_Documentation.pdf scripts/docgen/project_documentation.html
```

The prose lives in `doc_body_a.py` (system, data flow, backend, API) and `doc_body_b.py`
(interface, traces, results, operations, glossary); `doc_gen.py` holds the styling and the
table builders. Generated `.json` and `.html` files are intermediates and are not committed.
