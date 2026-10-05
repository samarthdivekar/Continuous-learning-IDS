"""Printable one-page incident report (browser -> Print -> Save as PDF).

Plain HTML with inline styles, no JavaScript and no external assets, so it prints
identically from any browser and can be attached to a ticket or an email. Every
value comes from the report payload built by MLService.incident_report; nothing
is invented here.
"""
from __future__ import annotations

from html import escape

ACTION_TEXT = {
    "block_source": "Block the attacking host",
    "rate_limit_to_victim": "Rate-limit traffic to the victim",
    "isolate_host": "Isolate the host",
    "investigate": "Investigate manually",
}

CSS = """
 body{font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;color:#15202b;max-width:820px;margin:32px auto;padding:0 20px}
 h1{font-size:23px;margin:0 0 2px} h2{font-size:15px;margin:26px 0 8px;border-bottom:1px solid #dde3ea;padding-bottom:4px}
 .sub{color:#5b6b7c;margin:0 0 18px;font-size:13px}
 table{border-collapse:collapse;width:100%;font-size:13.5px} td,th{border-bottom:1px solid #e6ebf1;padding:6px 8px;text-align:left;vertical-align:top}
 th{color:#5b6b7c;font-weight:600;width:230px}
 .tag{display:inline-block;border-radius:999px;padding:1px 10px;font-size:12px;border:1px solid #c7d0da}
 .crit{background:#fdeaea;border-color:#e9a4a4;color:#8d1f1f} .dry{background:#eef3f9;color:#2c5a8d}
 pre{background:#f5f7fa;border:1px solid #e3e9f0;border-radius:6px;padding:9px;font-size:12px;white-space:pre-wrap;margin:6px 0}
 .note{color:#5b6b7c;font-size:12px} .mono{font-family:ui-monospace,Consolas,monospace}
 @media print{body{margin:0}.noprint{display:none}}
"""


def fmt_value(value) -> str:
    """Readable feature values: 56737.0 -> "56,737", 0.0 -> "0", 8923.44 -> "8,923.4".
    Never scientific notation, which is unreadable for ports and packet counts."""
    if value is None:
        return ""
    v = float(value)
    if abs(v) >= 1e12:
        return f"{v:.3e}"
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.4g}" if abs(v) >= 1e-4 else f"{v:.2e}"


def _row(label: str, value: str) -> str:
    return f"<tr><th>{escape(label)}</th><td>{value}</td></tr>"


def incident_report_html(rep: dict) -> str:
    inc, ev = rep["incident"], rep.get("evidence")
    pr = inc.get("proposed") or {}
    rules = pr.get("rules") or {}
    sev = "crit" if inc.get("severity", 0) >= 6 else ""
    true_share = inc.get("true_attack_share")
    facts = [
        _row("Category", f'<b>{escape(str(inc["category"]))}</b> <span class="tag {sev}">severity '
                         f'{float(inc.get("severity", 0)):.1f}</span>'),
        _row("Key host", f'<span class="mono">{escape(str(inc["key_host"]))}</span> ({escape(str(inc["key_role"]))}, '
                         f'{inc.get("key_host_flows", 0):,} flows)'),
        _row("Size", f'{inc["n_flows"]:,} flagged flows · {inc["n_sources"]:,} source host(s) → '
                     f'{inc["n_destinations"]:,} destination host(s)'),
        _row("Model confidence", f'{float(inc.get("mean_confidence", 0)) * 100:.1f} %'),
    ]
    if inc.get("start"):
        facts.append(_row("Time range", f'{escape(str(inc["start"]))} → {escape(str(inc["end"]))}'))
    if true_share is not None:
        facts.append(_row("Ground truth (demo data)",
                          f"{float(true_share) * 100:.0f} % of these flows are truly malicious"))

    evidence_html = '<p class="note">No per-flow explanation available for this model.</p>'
    if ev:
        def feature_row(f: dict) -> str:
            shown = fmt_value(f.get("value"))
            return (f"<tr><td>{escape(str(f['label']))}</td><td>{shown}</td>"
                    f"<td>{escape(str(f['direction']))} the verdict</td></tr>")

        feats = "".join(feature_row(f) for f in ev.get("features", [])[:6])
        st = ev.get("structure", {})
        evidence_html = (
            f'<p>{escape(str(ev.get("summary", "")))}</p>'
            f'<table><tr><th>Feature</th><th>Value</th><th>Effect</th></tr>{feats}</table>'
            f'<p class="note">Example flow <span class="mono">{escape(str(ev.get("src_ip", "")))} → '
            f'{escape(str(ev.get("dst_ip", "")))}</span>; the source contacted '
            f'{st.get("source_distinct_peers", 0)} host(s)'
            + (f' across {st["source_distinct_ports"]} port(s)' if st.get("source_distinct_ports") else "")
            + f'. Attribution is gradient × input: what the decision is most sensitive to, not proof of cause.</p>')

    rule_html = "".join(f"<p class='note'>{escape(os_name)}</p><pre>{escape(rule)}</pre>"
                        for os_name, rule in (("Linux (iptables)", rules.get("linux")),
                                              ("Windows Firewall", rules.get("windows"))) if rule)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Incident {inc['incident_id']} · {escape(str(inc['category']))}</title><style>{CSS}</style></head><body>
<h1>Incident {inc['incident_id']} — {escape(str(inc['category']))}</h1>
<p class="sub">Window {rep['window_id']} · detector {escape(str(rep['model']))} · dataset {escape(str(rep['dataset']))}
 · generated {escape(str(rep['generated_at']))}</p>
<h2>What happened</h2><table>{''.join(facts)}</table>
<h2>Why it was flagged</h2>{evidence_html}
<h2>Proposed containment <span class="tag dry">dry run — not executed</span></h2>
<table>{_row('Action', f'<b>{escape(ACTION_TEXT.get(pr.get("action", ""), str(pr.get("action", "—"))))}</b>')}
{_row('Target', f'<span class="mono">{escape(str(pr.get("target", "—")))}</span>')}
{_row('Rationale', escape(str(pr.get('rationale', ''))))}</table>
{rule_html}
<p class="note">This system proposes; a human decides. Approval is recorded as a dry run and no rule is applied
to any device.</p>
<p class="noprint note">Use your browser's Print dialog and choose “Save as PDF”.</p>
</body></html>"""
