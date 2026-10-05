"""SIEM (CEF) export and the printable incident report. Both are pure functions over a
report payload, so they run without the ML stack."""
from src.api.report_html import incident_report_html
from src.product.siem import incident_to_cef, incidents_to_cef

INCIDENT = {
    "incident_id": 1, "category": "PortScan", "key_host": "172.16.0.1", "key_role": "source",
    "key_host_flows": 4986, "n_flows": 4986, "n_sources": 1, "n_destinations": 1,
    "mean_confidence": 0.999, "severity": 8.5, "true_attack_share": 1.0,
    "start": "2017-07-07T17:52:40.332397", "end": "2017-07-07T17:52:47.175884",
    "proposed": {"action": "block_source", "target": "172.16.0.1", "rationale": "scan from this host",
                 "rules": {"linux": "iptables -I INPUT -s 172.16.0.1 -j DROP",
                           "windows": "New-NetFirewallRule -DisplayName x -RemoteAddress 172.16.0.1 -Action Block"}},
}
REPORT = {"generated_at": "2026-10-05T12:00:00+00:00", "window_id": 363, "model": "gnn_ewc_replay",
          "dataset": "cicids2017", "label_mode": "multiclass", "threshold": 0.0, "incident": INCIDENT,
          "window_metrics": {"incidents": 1, "incident_precision": 1.0},
          "evidence": {"summary": "Flagged as PortScan with 100% confidence.",
                       "features": [{"label": "destination port", "value": 56737.0, "direction": "against"},
                                    {"label": "fwd packet length mean", "value": 0.0, "direction": "towards"},
                                    {"label": "protocol", "value": None, "direction": "towards"}],
                       "structure": {"source_distinct_peers": 1, "source_distinct_ports": 996},
                       "src_ip": "172.16.0.1", "dst_ip": "192.168.10.50"}}


def test_cef_line_is_well_formed():
    line = incident_to_cef(INCIDENT, window_id=363, model="gnn_ewc_replay")
    assert line.startswith("CEF:0|ContinualGNN|GNN-IDS|1.0|PortScan-incident|")
    header, body = line.split("|", 7)[:7], line.split("|", 7)[7]
    assert 0 <= int(header[6]) <= 10                      # severity within the CEF range
    fields = dict(kv.split("=", 1) for kv in body.split(" ") if "=" in kv)
    assert fields["src"] == "172.16.0.1" and fields["cnt"] == "4986"
    assert fields["cs1"] == "gnn_ewc_replay" and fields["cs2"] == "block_source"
    assert fields["externalId"] == "363-1"


def test_cef_escapes_separators_and_handles_many():
    nasty = {**INCIDENT, "category": "We|ird\\One",
             "proposed": {**INCIDENT["proposed"], "rationale": "a=b\nsecond line"}}
    line = incident_to_cef(nasty, 1, "m")
    assert r"We\|ird" in line and r"a\=b" in line and "\n" not in line
    assert len(incidents_to_cef([INCIDENT, INCIDENT], 363, "m").splitlines()) == 2


def test_report_html_contains_the_facts_and_the_dry_run_warning():
    html = incident_report_html(REPORT)
    for fragment in ("Incident 1", "PortScan", "172.16.0.1", "4,986", "996 port",
                     "iptables -I INPUT -s 172.16.0.1 -j DROP", "dry run", "gradient × input"):
        assert fragment in html, fragment
    assert "<script" not in html.lower()                  # printable, no scripting
    assert "56,737" in html and "5.674e" not in html      # readable, never scientific notation
    assert "None" not in html                             # a missing value renders empty


def test_report_html_without_evidence_still_renders():
    html = incident_report_html({**REPORT, "evidence": None})
    assert "No per-flow explanation available" in html and "Proposed containment" in html
