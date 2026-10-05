"""SIEM export (ArcSight CEF) for incidents.

An incident becomes one CEF line, the format most SIEMs (Splunk, QRadar, ArcSight,
Sentinel via syslog) can ingest without a custom parser. Nothing is sent anywhere:
the caller receives text and decides what to do with it, which keeps the "dry run
only" rule of the response layer.

CEF:0|Vendor|Product|Version|SignatureID|Name|Severity|Extension
Severity is 0-10; we map the incident's own severity (log size x confidence).
"""
from __future__ import annotations

from datetime import datetime, timezone

VENDOR, PRODUCT, VERSION = "ContinualGNN", "GNN-IDS", "1.0"
# CEF reserves | = \ in the header and = \ in extensions
_HEADER_ESCAPE = str.maketrans({"\\": r"\\", "|": r"\|"})
_EXT_ESCAPE = str.maketrans({"\\": r"\\", "=": r"\=", "\n": r"\n", "\r": r"\n"})


def _sev(incident: dict) -> int:
    """Incident severity (log1p(flows) x mean confidence) -> CEF 0-10."""
    return max(1, min(10, int(round(float(incident.get("severity", 0)) * 1.2))))


def _ts(value) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%b %d %Y %H:%M:%S")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%b %d %Y %H:%M:%S")
    except ValueError:
        return str(value)


def incident_to_cef(incident: dict, window_id: int, model: str, host: str = "gnn-ids") -> str:
    cat = str(incident.get("category", "Attack"))
    name = f"{cat} incident on {incident.get('key_host', '?')}"
    proposed = incident.get("proposed") or {}
    ext = {
        "rt": _ts(incident.get("start")),
        "end": _ts(incident.get("end")),
        "src": incident.get("key_host") if incident.get("key_role") == "source" else "",
        "dst": incident.get("key_host") if incident.get("key_role") == "destination" else "",
        "cnt": incident.get("n_flows"),
        "cs1Label": "detector", "cs1": model,
        "cs2Label": "proposedAction", "cs2": proposed.get("action", "investigate"),
        "cs3Label": "confidence", "cs3": f"{float(incident.get('mean_confidence', 0)):.3f}",
        "cs4Label": "windowId", "cs4": window_id,
        "cn1Label": "sourceHosts", "cn1": incident.get("n_sources"),
        "cn2Label": "destinationHosts", "cn2": incident.get("n_destinations"),
        "dvchost": host,
        "msg": proposed.get("rationale", ""),
        "externalId": f"{window_id}-{incident.get('incident_id')}",
    }
    body = " ".join(f"{k}={str(v).translate(_EXT_ESCAPE)}" for k, v in ext.items() if v not in (None, ""))
    header = "|".join(x.translate(_HEADER_ESCAPE) for x in
                      [VENDOR, PRODUCT, VERSION, f"{cat}-incident", name, str(_sev(incident))])
    return f"CEF:0|{header}|{body}"


def incidents_to_cef(incidents: list[dict], window_id: int, model: str, host: str = "gnn-ids") -> str:
    return "\n".join(incident_to_cef(i, window_id, model, host) for i in incidents)
