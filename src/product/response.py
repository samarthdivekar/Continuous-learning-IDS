"""Response actions with human approval (improvement 15) — DRY RUN ONLY.

For an incident the system PROPOSES a containment action and the exact firewall
rule that would implement it. Nothing is executed: an analyst must approve or
reject each proposal, and even an approved action is only recorded (status
"approved — dry run"). Wiring approved rules to a real firewall/SOAR is a
deployment decision deliberately left out of this project.
"""
from __future__ import annotations

import ipaddress

# categories where blocking the key SOURCE host is the natural containment
SOURCE_BLOCK = {"BruteForce", "PortScan", "WebAttack", "Botnet", "Infiltration", "DoS", "Attack"}


def _valid_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def propose_action(incident: dict) -> dict:
    """Return {action, target, rationale, rules{windows, linux}} for one incident."""
    cat, key, role = incident["category"], incident["key_host"], incident["key_role"]
    if not _valid_ip(key):
        return {"action": "investigate", "target": key, "rationale": "key host is not an IP address", "rules": {}}
    if cat == "DDoS" or (role == "destination" and incident["n_sources"] > 20):
        action, target = "rate_limit_to_victim", key
        rationale = (f"{incident['n_sources']} sources are flooding {key}; blocking sources one by one does not "
                     "scale, so rate-limit or filter traffic to the victim upstream.")
        rules = {"linux": f"iptables -A INPUT -d {key} -m hashlimit --hashlimit-above 200/sec "
                          f"--hashlimit-mode srcip --hashlimit-name ddos_{key.replace('.', '_')} -j DROP",
                 "windows": f"# rate limiting is not available in Windows Firewall; apply upstream for {key}"}
    elif cat in SOURCE_BLOCK and role == "source":
        action, target = "block_source", key
        rationale = (f"{key} originated {incident['key_host_flows']} flagged {cat} flows to "
                     f"{incident['n_destinations']} host(s); block it at the perimeter pending investigation.")
        rules = {"linux": f"iptables -I INPUT -s {key} -j DROP",
                 "windows": f'New-NetFirewallRule -DisplayName "GNN-IDS block {key}" -Direction Inbound '
                            f"-RemoteAddress {key} -Action Block"}
    else:
        action, target = "isolate_host", key
        rationale = f"{key} is the focal host of a {cat} incident; isolate it for forensic review."
        rules = {"linux": f"iptables -I FORWARD -s {key} -j DROP && iptables -I FORWARD -d {key} -j DROP",
                 "windows": f'New-NetFirewallRule -DisplayName "GNN-IDS isolate {key}" -Direction Outbound '
                            f"-RemoteAddress {key} -Action Block"}
    return {"action": action, "target": target, "rationale": rationale, "rules": rules, "dry_run": True}
