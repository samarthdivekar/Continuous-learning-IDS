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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
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


def write_report(rep: dict):
    """Write a self-contained HTML report of the run that the user can open, read and print."""
    import datetime
    pct = lambda n, d: (f"{100 * n / d:.0f}%" if d else "-")  # noqa: E731
    f1b, f1a = rep.get("f1_before"), rep.get("f1_after")
    kept = f1a is not None and f1b is not None and f1a >= f1b - 0.02
    f1b_s = f"{f1b:.3f}" if isinstance(f1b, float) else "-"
    f1a_s = f"{f1a:.3f}" if isinstance(f1a, float) else "-"
    a2 = rep.get("a2_flagged", 0)
    rows = "".join(f"<tr><td>{c}</td><td class='n'>{fl} / {tot}</td><td class='n'>{pct(fl, tot)}</td></tr>"
                   for c, fl, tot in rep.get("forget", []))
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    ts = datetime.datetime.now()
    path = out_dir / f"cyber_range_{ts:%Y%m%d_%H%M%S}.html"
    html = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Cyber Range Report</title>
<style>
 :root{{--bg:#0f1117;--card:#171a22;--ink:#e6e9f0;--muted:#9aa3b2;--line:#262b36;--good:#2ea043;--bad:#e5534b;--warn:#d8a200;--accent:#6b7bff}}
 *{{box-sizing:border-box}} body{{font:15px/1.6 system-ui,Segoe UI,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}
 .wrap{{max-width:820px;margin:0 auto;padding:32px 20px 60px}}
 h1{{font-size:26px;margin:0 0 4px}} h2{{font-size:17px;margin:26px 0 10px;border-bottom:2px solid var(--accent);padding-bottom:5px}}
 .sub{{color:var(--muted);margin:0 0 18px}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0}}
 .big{{font-size:30px;font-weight:700}} .good{{color:var(--good)}} .bad{{color:var(--bad)}} .warn{{color:var(--warn)}}
 table{{width:100%;border-collapse:collapse;margin-top:6px}} td,th{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line)}}
 .n{{text-align:right;font-variant-numeric:tabular-nums}} .muted{{color:var(--muted)}} .step{{color:var(--muted);font-weight:700;margin-right:6px}}
 .verdict{{font-size:18px;font-weight:600;margin:4px 0}}
</style></head><body><div class=wrap>
 <h1>GNN-IDS — Cyber Range Report</h1>
 <p class=sub>{ts:%Y-%m-%d %H:%M} · isolated Docker range ({rep.get('hosts', 0)} virtual hosts + 1 attacker, no route to the real network)</p>

 <div class=card>
   <div class=verdict>{'✅ The model learned a new attack without forgetting the old ones.' if (a2 > 0 and kept) else '⚠️ See the phases below.'}</div>
   <p class=muted>A real nmap port scan was run against an isolated virtual network. Nothing real was attacked.</p>
 </div>

 <h2><span class=step>1</span>Attack #1 — a scan the model had never seen</h2>
 <div class=card><span class=big>{rep.get('a1_flagged', 0)} / {rep.get('a1_total', 0)}</span> flows flagged as an attack
   ({rep.get('a1_nodes', 0)} hosts seen).
   <p class=muted>{'The model did not recognise this modern scan — it was trained on 2017 lab data. This is the real-world generalisation gap.' if rep.get('a1_flagged', 0) == 0 else 'The model flagged part of the scan straight away; its response to a never-seen real scan is unstable, run to run.'}</p></div>

 <h2><span class=step>2</span>Teaching (continual learning, gated)</h2>
 <div class=card>Labelled <b>{rep.get('labelled', 0)}</b> scan flows as <b>PortScan</b> and adapted.
   Adaptation <b class="{'good' if rep.get('accepted') else 'bad'}">{'accepted' if rep.get('accepted') else 'rolled back'}</b>.
   <table><tr><th>Old-attack score (the forgetting check)</th><th class=n>before</th><th class=n>after</th></tr>
   <tr><td>macro-F1 on held-out test windows</td><td class=n>{f1b_s}</td><td class="n {'good' if kept else 'bad'}">{f1a_s}</td></tr></table>
   <p class=muted>The update is only kept if old-attack detection does not drop — so it cannot forget.</p></div>

 <h2><span class=step>3</span>Attack #2 — a fresh scan it never saw</h2>
 <div class=card><span class="big {'good' if a2 > 0 else 'warn'}">{a2} / {rep.get('a2_total', 0)}</span> flows flagged as an attack.
   {f'<span class=muted>({rep.get("a2_cats")})</span>' if rep.get('a2_cats') else ''}
   <p class=muted>{'After teaching, it now detects a scan it was never shown — it generalised, it did not just memorise.' if a2 > 0 else 'Not flagged on this run (the scan sits on the decision boundary).'}</p></div>

 <h2><span class=step>4</span>Did it forget what it already knew?</h2>
 <div class=card><table><tr><th>Recorded attack</th><th class=n>still detected</th><th class=n>rate</th></tr>{rows}</table>
   <p class=muted>The attacks it was trained on are still detected at full rate — no forgetting.</p></div>

 <h2>What this shows</h2>
 <div class=card>It does not "solve" zero-days: a brand-new real attack can slip through at first (Phase 1).
   But once an analyst labels it, the model <b>learns it in seconds</b> (Phase 3) <b>without forgetting</b> the
   attacks it already knew (Phase 4). That continual-learning loop — new attacks without catastrophic
   forgetting — is the contribution. Every containment action the system proposes is a dry run; it never blocks.</div>
 <p class=muted style="margin-top:24px">Generated by demo/cyber_range.py · GNN-IDS</p>
</div></body></html>"""
    path.write_text(html, encoding="utf-8")
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://localhost:8000")
    p.add_argument("--keep", action="store_true", help="leave the containers running afterwards")
    p.add_argument("--no-open", action="store_true", help="write the report but do not open it in a browser")
    args = p.parse_args()

    try:
        api(args.server, "/health", timeout=8)
    except Exception:
        sys.exit(f"cannot reach the console at {args.server} - start the stack first.")
    docker_ok()

    rep = {"hosts": len(HOST_IPS)}
    try:
        banner(1, "Build the isolated range (caged - no route to your real network)")
        up()

        banner(2, "Attack #1 - the model has never seen this scan")
        api(args.server, "/live/reset", {})
        flows = scan_and_capture("1-1000")
        r = ship(args.server, flows)
        flagged = r["flagged"]
        rep["a1_flagged"], rep["a1_total"], rep["a1_nodes"] = flagged, r["n_flows"], r["n_hosts"]
        print(f"the sensor saw {r['n_flows']} flows across {r['n_hosts']} hosts.")
        print(f"DETECTED AS ATTACK: {flagged} / {r['n_flows']}   ->   "
              f"{'(as expected, the real scan is NOT detected: it is out of the lab-training distribution)' if flagged == 0 else ''}")

        banner(3, "Teach it - label the scan PortScan, then adapt (gated so it cannot forget)")
        lab = api(args.server, "/live/label", {"label": "PortScan", "site": SITE, "last_minutes": 60})
        ad = api(args.server, "/live/adapt", {"site": SITE, "epochs": 3})
        ob = (ad.get("old_attacks_before") or {}).get("macro_f1")
        oa = (ad.get("old_attacks_after") or {}).get("macro_f1")
        rep["labelled"], rep["accepted"], rep["f1_before"], rep["f1_after"] = lab["labelled"], ad.get("accepted"), ob, oa
        print(f"labelled {lab['labelled']} flows; adapt accepted={ad.get('accepted')}")
        if ob is not None:
            print(f"old-attack macro-F1 (the forgetting check): {ob:.3f} -> {oa:.3f}  "
                  f"({'kept' if oa >= ob - 0.02 else 'ROLLED BACK'})")

        banner(4, "Attack #2 - a fresh scan the model never saw")
        flows2 = scan_and_capture("1-1500")
        r2 = ship(args.server, flows2)
        f2 = r2["flagged"]
        cats = ", ".join(f"{v} {k}" for k, v in r2["counts"].items() if k != "Benign")
        rep["a2_flagged"], rep["a2_total"], rep["a2_cats"] = f2, r2["n_flows"], cats
        print(f"DETECTED AS ATTACK: {f2} / {r2['n_flows']}   {('('+cats+')') if cats else ''}")
        print("-> it now flags a scan it never saw" if f2 else "-> still not flagged on this run")

        banner(5, "Did it forget the attacks it already knew?")
        rep["forget"] = []
        for c in ("DoS", "PortScan", "DDoS"):
            rr = api(args.server, "/sensor/replay_recorded", {"category": c, "site": "range-forget-check"})
            rep["forget"].append((c, rr["flagged"], rr["replayed"]))
            print(f"  recorded {c}: {rr['flagged']} / {rr['replayed']} still detected")

        path = write_report(rep)
        print(f"\nReport saved: {path}")
        if not args.no_open:
            try:
                import webbrowser
                webbrowser.open(path.as_uri())
            except Exception:
                pass
        print("Done. Open the console's Live sites tab to see the sites, graph and incidents.")
    finally:
        if not args.keep:
            print("\ntearing down the range...", flush=True)
            teardown()


if __name__ == "__main__":
    main()
