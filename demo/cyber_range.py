"""Self-contained cyber range: an isolated virtual network, an attacker, and the IDS - no real machines.

    python demo/cyber_range.py --server http://localhost:8000

Spins up a caged Docker network (no route to your real network or the internet), starts several "host"
containers on it, and one "attacker" container. The attacker runs an nmap PORT SCAN (reconnaissance only -
never a DoS or anything destructive) across the hosts while the IDS sensor captures the segment's traffic.
The capture is converted with the pinned CICFlowMeter and scored by the live model on the central console,
so the whole attack-and-detect loop runs on one machine.

It walks the continual-learning story end to end:
  1. the real scan is scored BENIGN  (the lab-trained model has never seen it),
  2. you teach it (label PortScan, adapt - gated so it cannot forget),
  3. a fresh scan is now DETECTED,
  4. the recorded attacks still detect (no forgetting).

Safety: the attacker container is on an `--internal` network with no gateway, so it can only reach the
throwaway host containers in this range - never your PC, your Wi-Fi, or the internet. The only attack it
runs is a port scan. Everything is torn down at the end.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live.flowmeter import FlowMeterError, pcap_to_flows  # noqa: E402

NET = "gnnids-range"
SUBNET = "10.88.0.0/24"
ATTACKER_IMAGE = "gnnids-attacker"
HOST_IPS = [f"10.88.0.{i}" for i in (11, 12, 13, 14, 15, 16)]
ATTACKER_IP = "10.88.0.100"
SITE = "cyber-range"


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


def api(server, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(server.rstrip("/") + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {},
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def docker_ok():
    if sh(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode != 0:
        sys.exit("Docker Desktop is not running. Start it and try again.")
    for img in (ATTACKER_IMAGE, "gnnids-cicflowmeter"):
        if sh(["docker", "image", "inspect", img]).returncode != 0:
            if img == ATTACKER_IMAGE:
                print(f"building {img} (one-time)...", flush=True)
                root = Path(__file__).resolve().parent.parent
                df = root / "sensor" / "_lab" / "attacker.Dockerfile"
                df.parent.mkdir(parents=True, exist_ok=True)
                df.write_text("FROM alpine:3.20\nRUN apk add --no-cache nmap tcpdump\n")
                if sh(["docker", "build", "-t", ATTACKER_IMAGE, "-f", str(df), str(df.parent)]).returncode != 0:
                    sys.exit("could not build the attacker image")
            else:
                sys.exit(f"flow-meter image '{img}' missing: docker build -t {img} "
                         f"-f sensor/cicflowmeter.Dockerfile sensor")


def teardown():
    for i in (11, 12, 13, 14, 15, 16):
        sh(["docker", "rm", "-f", f"gnnids-h{i}"])
    sh(["docker", "network", "rm", NET])


def up():
    teardown()
    # --internal: no gateway, so nothing on this network can reach the host, the LAN or the internet
    if sh(["docker", "network", "create", "--internal", "--subnet", SUBNET, NET]).returncode != 0:
        sys.exit("could not create the isolated network")
    ports = "21 22 23 25 80 110 139 143 443 445 3306 3389 8080"
    for ip in HOST_IPS:
        name = f"gnnids-h{ip.split('.')[-1]}"
        sh(["docker", "run", "-d", "--rm", "--name", name, "--network", NET, "--ip", ip, "alpine:3.20",
            "sh", "-c", f"for p in {ports}; do (nc -lk -p $p >/dev/null 2>&1 &); done; sleep 1200"])
    time.sleep(2)
    print(f"isolated range up: {len(HOST_IPS)} hosts on {SUBNET} (no route out), attacker at {ATTACKER_IP}")


def scan_and_capture(port_range: str) -> list[dict]:
    """Attacker runs an nmap SYN scan across the range while capturing; returns the flows the sensor sees."""
    with tempfile.TemporaryDirectory(prefix="gnnids_range_") as tmp:
        tmp = Path(tmp)
        targets = " ".join(HOST_IPS)
        script = (f"tcpdump -i eth0 -w /data/scan.pcap -U >/dev/null 2>&1 & TD=$!; sleep 2; "
                  f"nmap -sS -T4 -p {port_range} {targets} >/dev/null 2>&1; sleep 3; kill $TD 2>/dev/null; sleep 1")
        r = subprocess.run(["docker", "run", "--rm", "--network", NET, "--ip", ATTACKER_IP,
                            "-v", f"{tmp}:/data", ATTACKER_IMAGE, "sh", "-c", script],
                           capture_output=True, text=True, env={"MSYS_NO_PATHCONV": "1", **_env()})
        pcap = tmp / "scan.pcap"
        if not pcap.exists():
            sys.exit(f"capture failed: {(r.stderr or r.stdout)[:300]}")
        try:
            return pcap_to_flows(pcap)
        except FlowMeterError as exc:
            sys.exit(f"flow meter: {exc}")


def _env():
    import os
    return dict(os.environ)


def ship(server, flows):
    return api(server, "/sensor/flows", {"site": SITE, "flows": flows, "source": "replay"})


def banner(step, text):
    print(f"\n{'='*64}\n  {step}. {text}\n{'='*64}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://localhost:8000")
    p.add_argument("--keep", action="store_true", help="leave the containers running afterwards")
    args = p.parse_args()

    try:
        api(args.server, "/health", timeout=8)
    except Exception:
        sys.exit(f"cannot reach the console at {args.server} - start the stack first.")
    docker_ok()

    try:
        banner(1, "Build the isolated range (caged - no route to your real network)")
        up()

        banner(2, "Attack #1 - the model has never seen this scan")
        api(args.server, "/live/reset", {})
        flows = scan_and_capture("1-1000")
        r = ship(args.server, flows)
        flagged = r["flagged"]
        print(f"the sensor saw {r['n_flows']} flows across {r['n_hosts']} hosts.")
        print(f"DETECTED AS ATTACK: {flagged} / {r['n_flows']}   ->   "
              f"{'(as expected, the real scan is NOT detected: it is out of the lab-training distribution)' if flagged == 0 else ''}")

        banner(3, "Teach it - label the scan PortScan, then adapt (gated so it cannot forget)")
        lab = api(args.server, "/live/label", {"label": "PortScan", "site": SITE, "last_minutes": 60})
        ad = api(args.server, "/live/adapt", {"site": SITE, "epochs": 3})
        ob = (ad.get("old_attacks_before") or {}).get("macro_f1")
        oa = (ad.get("old_attacks_after") or {}).get("macro_f1")
        print(f"labelled {lab['labelled']} flows; adapt accepted={ad.get('accepted')}")
        if ob is not None:
            print(f"old-attack macro-F1 (the forgetting check): {ob:.3f} -> {oa:.3f}  "
                  f"({'kept' if oa >= ob - 0.02 else 'ROLLED BACK'})")

        banner(4, "Attack #2 - a fresh scan the model never saw")
        flows2 = scan_and_capture("1-1500")
        r2 = ship(args.server, flows2)
        f2 = r2["flagged"]
        cats = ", ".join(f"{v} {k}" for k, v in r2["counts"].items() if k != "Benign")
        print(f"DETECTED AS ATTACK: {f2} / {r2['n_flows']}   {('('+cats+')') if cats else ''}")
        print("-> it now flags a scan it never saw" if f2 else "-> still not flagged on this run")

        banner(5, "Did it forget the attacks it already knew?")
        for c in ("DoS", "PortScan", "DDoS"):
            rr = api(args.server, "/sensor/replay_recorded", {"category": c, "site": "range-forget-check"})
            print(f"  recorded {c}: {rr['flagged']} / {rr['replayed']} still detected")

        print("\nDone. Open the console's Live sites tab to see the sites, graph and incidents.")
    finally:
        if not args.keep:
            print("\ntearing down the range...", flush=True)
            teardown()


if __name__ == "__main__":
    main()
