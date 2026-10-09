"""Self-contained cyber range, streamed LIVE into the console: an isolated virtual network with normal
traffic, an attacker, and the IDS watching as it happens.

    python demo/cyber_range.py --server http://127.0.0.1:8000

The range runs on a caged Docker network (`--internal`: no route to your PC, your LAN or the internet):

  * 6 server hosts (10.88.0.11-16) offering web and a few TCP services. Each runs its own capture
    (tcpdump, rotated every few seconds) - one sensor per machine, like `sensor/agent.py` on a real host.
  * 2 workstations (10.88.0.21-22) making ordinary requests to the servers the whole time, so the
    console sees normal traffic as well as the attack, and false alarms are measured, not assumed.
  * 1 attacker (10.88.0.100) that runs an nmap PORT SCAN when the script says so (reconnaissance only -
    never a DoS or anything destructive).

While it runs, a streamer on this PC picks up every finished capture chunk, converts it with the pinned
CICFlowMeter and sends it to the console (POST /sensor/flows, site "cyber-range"), where it is scored
inside the site's recent traffic and shown in Live sites within seconds. The same chunks also give exact
ground truth: a flow is attack traffic if and only if the attacker's address is one of its two ends.

The run, end to end:
  1. normal traffic only           -> false-alarm rate of the lab-trained model on this network
  2. attack #1: SYN scan, ports 1-1000          -> detected? (usually not: out of the lab distribution)
  3. teach: the analyst labels the scan's flows PortScan and the normal phase's flows Benign; the model
     adapts, gated (rolled back if old-attack macro-F1 drops or false alarms rise)
  4. normal traffic again          -> false-alarm rate after teaching
  5. attack #2: a DIFFERENT scan - TCP connect scan, other ports, other timing -> detected now?
  6. recorded dataset attacks replayed -> still detected (no forgetting)
A self-contained HTML report with every number is written to reports/ and opened.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.live.flowmeter import FlowMeterError, pcaps_to_flows  # noqa: E402

NET = "gnnids-range"
SUBNET = "10.88.0.0/24"
IMAGE = "gnnids-range"
SERVERS = [f"10.88.0.{i}" for i in (11, 12, 13, 14, 15, 16)]
CLIENTS = ["10.88.0.21", "10.88.0.22"]
ATTACKER_IP = "10.88.0.100"
SITE = "cyber-range"
CHUNK_SECONDS = 3
SERVICE_PORTS = "21 22 23 25 110 143 443 445 3306 3389 8080"


def sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, env={**os.environ, "MSYS_NO_PATHCONV": "1"}, **kw)


def api(server, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if os.environ.get("GNNIDS_API_KEY"):
        headers["X-API-Key"] = os.environ["GNNIDS_API_KEY"]
    req = urllib.request.Request(server.rstrip("/") + path, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def docker_ok():
    if sh(["docker", "info", "--format", "{{.ServerVersion}}"]).returncode != 0:
        sys.exit("Docker Desktop is not running. Start it and try again.")
    if sh(["docker", "image", "inspect", "gnnids-cicflowmeter"]).returncode != 0:
        sys.exit("flow-meter image missing: docker build -t gnnids-cicflowmeter -f sensor/cicflowmeter.Dockerfile sensor")
    if sh(["docker", "image", "inspect", IMAGE]).returncode != 0:
        print(f"building {IMAGE} (one-time, needs internet for the base image)...", flush=True)
        df = ROOT / "sensor" / "_lab" / "range.Dockerfile"
        r = sh(["docker", "build", "-t", IMAGE, "-f", str(df), str(df.parent)])
        if r.returncode != 0:
            sys.exit(f"could not build the range image: {r.stderr[-400:]}")


def names():
    return ([f"gnnids-h{ip.split('.')[-1]}" for ip in SERVERS] + [f"gnnids-ws{ip.split('.')[-1]}" for ip in CLIENTS]
            + ["gnnids-attacker"])


def teardown():
    for n in names():
        sh(["docker", "rm", "-f", n])
    sh(["docker", "network", "rm", NET])


def up(capdir: Path):
    teardown()
    # --internal: no gateway, so nothing on this network can reach the host, the LAN or the internet
    if sh(["docker", "network", "create", "--internal", "--subnet", SUBNET, NET]).returncode != 0:
        sys.exit("could not create the isolated network")
    for ip in SERVERS:
        name = f"gnnids-h{ip.split('.')[-1]}"
        d = capdir / name
        d.mkdir(parents=True, exist_ok=True)
        script = ("mkdir -p /www && echo '<h1>intranet</h1>' > /www/index.html && httpd -p 80 -h /www; "
                  f"for p in {SERVICE_PORTS}; do (nc -lk -p $p -e cat >/dev/null 2>&1 &); done; "
                  f"exec tcpdump -i eth0 -n -U -Z root -G {CHUNK_SECONDS} -w /cap/c_%s.pcap 2>/dev/null")
        r = sh(["docker", "run", "-d", "--rm", "--name", name, "--network", NET, "--ip", ip,
                "-v", f"{d}:/cap", IMAGE, "sh", "-c", script])
        if r.returncode != 0:
            sys.exit(f"could not start {name}: {r.stderr[-300:]}")
    targets = " ".join(SERVERS)
    for ip in CLIENTS:      # ordinary office traffic: web pages and short service connections, all day long
        script = (f"set -- {targets}; while true; do i=$((RANDOM % 6 + 1)); eval t=\\${{$i}}; "
                  "wget -q -T 2 -O /dev/null http://$t/ 2>/dev/null; "
                  "if [ $((RANDOM % 3)) -eq 0 ]; then echo hello | nc -w 1 $t 22 >/dev/null 2>&1; fi; "
                  "if [ $((RANDOM % 5)) -eq 0 ]; then echo QUIT | nc -w 1 $t 25 >/dev/null 2>&1; fi; "
                  "sleep 0.$((RANDOM % 8 + 2)); done")
        sh(["docker", "run", "-d", "--rm", "--name", f"gnnids-ws{ip.split('.')[-1]}", "--network", NET, "--ip", ip,
            IMAGE, "sh", "-c", script])
    print(f"isolated range up on {SUBNET} (no route out): {len(SERVERS)} servers capturing, "
          f"{len(CLIENTS)} workstations browsing, attacker standing by at {ATTACKER_IP}", flush=True)


def scan(args_: str):
    """The attacker runs one nmap scan against the servers (reconnaissance only), then exits."""
    return sh(["docker", "run", "--rm", "--name", "gnnids-attacker", "--network", NET, "--ip", ATTACKER_IP,
               IMAGE, "sh", "-c", f"nmap {args_} {' '.join(SERVERS)} >/dev/null 2>&1"])


# ------------------------------------------------------------------ live streamer
class Streamer(threading.Thread):
    """Ships every finished capture chunk to the console as soon as it exists, and keeps the console's
    per-flow verdicts with exact ground truth for the report."""

    def __init__(self, server: str, capdir: Path):
        super().__init__(daemon=True)
        self.server, self.capdir = server, capdir
        self.phases: list[tuple[float, str]] = [(0.0, "setup")]
        self.shipped_until = 0.0                # every chunk that ENDED before this has reached the console
        self.stop_event = threading.Event()
        self.records: list[dict] = []           # one per flow: phase, attack?, flagged?, id, label
        self.latency: list[float] = []          # seconds from the end of a chunk to the console's verdict
        self.errors: list[str] = []
        self.chunks = 0
        self.lock = threading.Lock()

    def finished_chunks(self, final: bool) -> list[Path]:
        out = []
        for d in self.capdir.iterdir():
            files = sorted(d.glob("c_*.pcap"), key=lambda p: int(p.stem.split("_")[1]))
            out += files if final else files[:-1]           # the newest file is still being written
        return out

    @property
    def phase(self) -> str:
        return self.phases[-1][1]

    @phase.setter
    def phase(self, name: str):
        self.phases.append((time.time(), name))

    def phase_at(self, t: float) -> str:
        """The phase a chunk belongs to is the one running when it was CAPTURED, not when it was shipped."""
        name = self.phases[0][1]
        for start, n in self.phases:
            if t >= start:
                name = n
        return name

    def ship(self, final: bool = False):
        files = self.finished_chunks(final)
        if not files:
            return
        start_of = {str(f): int(f.stem.split("_")[1]) for f in files}
        newest_end = max(start_of.values()) + CHUNK_SECONDS
        try:
            flows = pcaps_to_flows(files, tag_source=True)
        except FlowMeterError as exc:
            self.errors.append(str(exc))
            return
        finally:
            for f in files:
                f.unlink(missing_ok=True)
        sources = [f.pop("source_pcap", None) for f in flows]
        if flows:
            try:
                res = api(self.server, "/sensor/flows", {"site": SITE, "flows": flows, "source": "pcap", "detail": True})
            except Exception as exc:                   # noqa: BLE001 - report, keep streaming
                self.errors.append(f"console: {exc}")
                return
            self.latency.append(max(0.0, time.time() - newest_end))
            self.chunks += 1
            kept = [(f, src) for f, src in zip(flows, sources) if f.get("protocol")]   # console drops non-IP records
            with self.lock:
                for (f, src), fid, lab, uns in zip(kept, res.get("flow_ids", []), res.get("labels", []),
                                                    res.get("unsure_flags") or [False] * len(kept)):
                    self.records.append({"phase": self.phase_at(start_of.get(src, newest_end)), "id": fid,
                                         "label": lab, "unsure": uns,
                                         "attack": ATTACKER_IP in (f["src_ip"], f["dst_ip"])})
        self.shipped_until = max(self.shipped_until, newest_end)
        if not flows:
            return
        flagged = res.get("flagged", 0)
        print(f"  [{time.strftime('%H:%M:%S')}] {len(files)} chunks -> console: {res['n_flows']} flows, "
              f"{flagged} flagged{'  <-- ALERT' if flagged else ''}  ({self.latency[-1]:.1f}s after capture)",
              flush=True)

    def run(self):
        while not self.stop_event.is_set():
            self.ship()
            self.stop_event.wait(1.0)

    def flush(self, timeout: float = 60.0):
        """Wait until every chunk captured up to now has been converted, scored and stored by the console."""
        target, t0 = time.time(), time.time()
        while self.shipped_until < target and time.time() - t0 < timeout:
            time.sleep(0.5)

    def stats(self, phase: str) -> dict:
        with self.lock:
            rs = [r for r in self.records if r["phase"] == phase]
        att = [r for r in rs if r["attack"]]
        ben = [r for r in rs if not r["attack"]]
        cats: dict[str, int] = {}
        for r in att:
            if r["label"] != "Benign":
                cats[r["label"]] = cats.get(r["label"], 0) + 1
        return {"attack_flows": len(att), "attack_detected": sum(r["label"] != "Benign" for r in att),
                "benign_flows": len(ben), "benign_flagged": sum(r["label"] != "Benign" for r in ben),
                "benign_alarms": sum(r["label"] != "Benign" and not r["unsure"] for r in ben),
                "attack_alarms": sum(r["label"] != "Benign" and not r["unsure"] for r in att),
                "categories": cats,
                "attack_ids": [r["id"] for r in att], "benign_ids": [r["id"] for r in ben]}


def banner(step, text):
    print(f"\n{'=' * 64}\n  {step}. {text}\n{'=' * 64}", flush=True)


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "-"


def line(st: dict, what: str) -> str:
    out = []
    if st["attack_flows"]:
        cats = ", ".join(f"{v} {k}" for k, v in st["categories"].items())
        out.append(f"attack flows detected: {st['attack_detected']} / {st['attack_flows']} "
                   f"({pct(st['attack_detected'], st['attack_flows'])}){f' as {cats}' if cats else ''}")
    out.append(f"normal flows wrongly flagged: {st['benign_flagged']} / {st['benign_flows']} "
               f"({pct(st['benign_flagged'], st['benign_flows'])}), raised as alarms after abstention: "
               f"{st['benign_alarms']}")
    return f"{what}: " + "; ".join(out)


# ------------------------------------------------------------------ report
def write_report(rep: dict) -> Path:
    import datetime
    import html as _h
    esc = lambda x: _h.escape(str(x))                                        # noqa: E731

    def row(name, st):
        a = f"{st['attack_detected']} / {st['attack_flows']} ({pct(st['attack_detected'], st['attack_flows'])})" \
            if st["attack_flows"] else "–"
        b = f"{st['benign_flagged']} / {st['benign_flows']} ({pct(st['benign_flagged'], st['benign_flows'])})"
        c = f"{st['benign_alarms']} ({pct(st['benign_alarms'], st['benign_flows'])})"
        cats = ", ".join(f"{v} {k}" for k, v in st["categories"].items()) or "–"
        return (f"<tr><td>{esc(name)}</td><td class=n>{a}</td><td>{esc(cats)}</td><td class=n>{b}</td>"
                f"<td class=n>{c}</td></tr>")

    p = rep["phases"]
    ad = rep.get("adapt") or {}
    ob, oa = (ad.get("old_attacks_before") or {}), (ad.get("old_attacks_after") or {})
    sh_ = ad.get("site_holdout") or {}
    f3 = lambda v: f"{v:.3f}" if isinstance(v, (int, float)) else "–"      # noqa: E731
    pc = lambda v: f"{100 * v:.2f}%" if isinstance(v, (int, float)) else "–"  # noqa: E731
    forget = "".join(f"<tr><td>{esc(c)}</td><td class=n>{fl} / {tot}</td><td class=n>{pct(fl, tot)}</td></tr>"
                     for c, fl, tot in rep.get("forget", []))
    a1, a2 = p["attack1"], p["attack2"]
    lat = rep.get("latency", {})
    verdict = []
    verdict.append("Scan #1 (never seen) was " + ("<b class=bad>not detected</b>" if a1["attack_detected"] == 0 else
                   f"detected for <b>{pct(a1['attack_detected'], a1['attack_flows'])}</b> of its flows") + ".")
    verdict.append(f"Teaching was <b class={'good' if ad.get('accepted') else 'bad'}>"
                   f"{'accepted' if ad.get('accepted') else 'rolled back'}</b>.")
    verdict.append(f"Scan #2 (a different technique) was detected for <b>{pct(a2['attack_detected'], a2['attack_flows'])}</b> "
                   f"of its flows, with <b>{pct(a2['benign_flagged'] + p['normal2']['benign_flagged'], a2['benign_flows'] + p['normal2']['benign_flows'])}</b> "
                   "of normal flows wrongly flagged after teaching.")
    ts = datetime.datetime.now()
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"cyber_range_{ts:%Y%m%d_%H%M%S}.html"
    path.write_text(f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Cyber Range Report</title>
<style>
 :root{{--bg:#0f1117;--card:#171a22;--ink:#e6e9f0;--muted:#9aa3b2;--line:#262b36;--good:#2ea043;--bad:#e5534b;--accent:#6b7bff}}
 *{{box-sizing:border-box}} body{{font:15px/1.6 system-ui,Segoe UI,sans-serif;margin:0;background:var(--bg);color:var(--ink)}}
 .wrap{{max-width:900px;margin:0 auto;padding:32px 16px 60px}} h1{{font-size:26px;margin:0 0 4px}}
 h2{{font-size:17px;margin:26px 0 10px;border-bottom:2px solid var(--accent);padding-bottom:5px}}
 .sub,.muted{{color:var(--muted)}} .card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:12px 0;overflow-x:auto}}
 .good{{color:var(--good)}} .bad{{color:var(--bad)}} table{{width:100%;border-collapse:collapse}}
 td,th{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}} .n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
</style></head><body><div class=wrap>
 <h1>GNN-IDS — Cyber Range Report</h1>
 <p class=sub>{ts:%Y-%m-%d %H:%M} · isolated Docker network: {len(SERVERS)} servers (each capturing its own traffic),
 {len(CLIENTS)} workstations making normal requests, 1 attacker · no route to the real network · streamed live to the console</p>
 <div class=card>{' '.join(verdict)}</div>

 <h2>Every phase, measured</h2>
 <div class=card><table><tr><th>Phase</th><th class=n>Attack flows detected</th><th>called</th><th class=n>Normal flows wrongly flagged</th>
 <th class=n>…raised as alarms (after abstention)</th></tr>
 {row("1 · Normal traffic only (before teaching)", p["normal1"])}
 {row("2 · Scan #1: nmap SYN scan, ports 1-1000", a1)}
 {row("4 · Normal traffic only (after teaching)", p["normal2"])}
 {row("5 · Scan #2: nmap TCP connect scan, ports 1001-2000", a2)}
 </table>
 <p class=muted>Ground truth is exact: a flow is attack traffic if and only if the attacker ({ATTACKER_IP}) is one of its two ends.
 "Normal flows wrongly flagged" is the false-positive rate on this network's own traffic; the last column is what reaches the
 analyst as an alarm once flows the model is unsure about (conformal abstention, α = 0.05) are sent to review instead.</p></div>

 <h2>3 · Teaching (gated)</h2>
 <div class=card>The analyst labelled {rep.get('taught_attack', 0)} scan-#1 flows <b>PortScan</b> and {rep.get('taught_benign', 0)}
 phase-1 flows <b>Benign</b>; every fifth normal flow was held back to measure false alarms. The update was
 <b class="{'good' if ad.get('accepted') else 'bad'}">{'accepted' if ad.get('accepted') else 'rolled back'}</b>{(' — ' + esc(ad.get('reason'))) if ad.get('reason') else ''}.
 <table><tr><th>Check (data the update did not train on)</th><th class=n>before</th><th class=n>after</th></tr>
 <tr><td>Old-attack macro-F1, recorded test windows</td><td class=n>{f3(ob.get('macro_f1'))}</td><td class=n>{f3(oa.get('macro_f1'))}</td></tr>
 <tr><td>False-positive rate, recorded benign traffic</td><td class=n>{pc(ob.get('fpr'))}</td><td class=n>{pc(oa.get('fpr'))}</td></tr>
 <tr><td>False-positive rate, this network's held-back normal traffic ({sh_.get('n_flows', 0)} flows)</td><td class=n>{pc(sh_.get('fpr_before'))}</td><td class=n>{pc(sh_.get('fpr_after'))}</td></tr>
 </table><p class=muted>Rolled back if macro-F1 drops by more than 0.02 or either false-positive rate rises by more than 0.5 points.
 Took {ad.get('seconds', '–')} s; the console kept scoring traffic meanwhile.</p></div>

 <h2>6 · Did it forget what it already knew?</h2>
 <div class=card><table><tr><th>Recorded dataset attack (replayed)</th><th class=n>flagged</th><th class=n>rate</th></tr>{forget}</table></div>

 <h2>How live was it?</h2>
 <div class=card>{rep.get('chunks', 0)} capture batches streamed to the console. From the end of a {CHUNK_SECONDS}-second capture chunk
 to the console's verdict: median <b>{lat.get('p50', '–')} s</b>, worst {lat.get('max', '–')} s (flow conversion + scoring).
 {('<p class=bad>Errors: ' + esc('; '.join(rep['errors'][:3])) + '</p>') if rep.get('errors') else ''}</div>

 <h2>What this does and does not show</h2>
 <div class=card><ul>
 <li>Detection and false alarms are measured on traffic the model scored live, with exact ground truth.</li>
 <li>Scan #2 uses a different technique, ports and timing from the scan that was taught, but the same attacker host
 and the same small network — it shows generalisation across scan types, not to any attack anywhere.</li>
 <li>The range's normal traffic is simple and synthetic; a real network's false-alarm rate must be measured on that network
 (<span class=muted>sensor/measure_fpr.py</span>).</li>
 <li>Nothing real was attacked; every proposed containment action in the console is a dry run.</li></ul></div>
 <p class=muted style="margin-top:24px">Generated by demo/cyber_range.py · GNN-IDS</p>
</div></body></html>""", encoding="utf-8")
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--normal-seconds", type=int, default=30, help="length of each normal-traffic phase")
    p.add_argument("--keep", action="store_true", help="leave the range running afterwards")
    p.add_argument("--no-open", action="store_true", help="write the report but do not open it in a browser")
    args = p.parse_args()

    try:
        api(args.server, "/health", timeout=8)
        model = api(args.server, "/live/model", timeout=120)
    except Exception:
        sys.exit(f"cannot reach the console at {args.server} - start the stack first.")
    if "max_fpr_rise" not in model:       # an older build (or another program on this port) answered
        sys.exit(f"the server at {args.server} is not the current GNN-IDS stack (restart it: scripts/run_stack.ps1).")
    docker_ok()

    capdir = Path(tempfile.mkdtemp(prefix="gnnids_range_"))
    streamer = Streamer(args.server, capdir)
    rep: dict = {"phases": {}}
    try:
        banner(1, "Build the isolated range and stream it live to the console (site 'cyber-range')")
        api(args.server, "/live/reset", {})
        up(capdir)
        print("Open the console -> Live sites -> CYBER-RANGE to watch.", flush=True)
        streamer.start()

        banner(2, f"Normal traffic only ({args.normal_seconds}s) - does the lab-trained model raise false alarms here?")
        streamer.phase = "normal1"
        time.sleep(args.normal_seconds)
        streamer.flush()
        rep["phases"]["normal1"] = st = streamer.stats("normal1")
        print(line(st, "normal phase"), flush=True)

        banner(3, "Attack #1 - nmap SYN scan, ports 1-1000 (the model has never seen this scan)")
        streamer.phase = "attack1"
        scan("-sS -T4 -p 1-1000")
        streamer.flush()
        time.sleep(CHUNK_SECONDS)
        rep["phases"]["attack1"] = a1 = streamer.stats("attack1")
        print(line(a1, "attack #1"), flush=True)

        banner(4, "Teach it - label the scan PortScan and the normal phase Benign, then adapt (gated)")
        streamer.phase = "teaching"
        n1 = rep["phases"]["normal1"]
        la = api(args.server, "/live/label", {"label": "PortScan", "flow_ids": a1["attack_ids"], "analyst": "cyber-range",
                                              "only_unlabelled": False}) if a1["attack_ids"] else {"labelled": 0}
        lb = api(args.server, "/live/label", {"label": "Benign", "flow_ids": n1["benign_ids"] + a1["benign_ids"],
                                              "analyst": "cyber-range", "only_unlabelled": False})
        rep["taught_attack"], rep["taught_benign"] = la["labelled"], lb["labelled"]
        ad = api(args.server, "/live/adapt", {"site": SITE, "epochs": 3})
        rep["adapt"] = ad
        ob, oa = ad.get("old_attacks_before") or {}, ad.get("old_attacks_after") or {}
        print(f"labelled {la['labelled']} scan flows PortScan, {lb['labelled']} normal flows Benign; "
              f"adaptation {'ACCEPTED' if ad.get('accepted') else 'ROLLED BACK: ' + str(ad.get('reason'))}")
        if ob:
            hold = ad.get("site_holdout") or {}
            print(f"  old-attack macro-F1 {ob['macro_f1']:.3f} -> {oa['macro_f1']:.3f}; recorded benign FPR "
                  f"{ob['fpr']:.2%} -> {oa['fpr']:.2%}; this network's held-back normal FPR "
                  f"{(hold.get('fpr_before') or 0):.2%} -> {(hold.get('fpr_after') or 0):.2%}", flush=True)

        banner(5, f"Normal traffic again ({args.normal_seconds}s) - false alarms after teaching")
        streamer.phase = "normal2"
        time.sleep(args.normal_seconds)
        streamer.flush()
        rep["phases"]["normal2"] = st = streamer.stats("normal2")
        print(line(st, "normal phase"), flush=True)

        banner(6, "Attack #2 - a DIFFERENT scan: TCP connect scan, ports 1001-2000, slower timing")
        streamer.phase = "attack2"
        scan("-sT -T3 -p 1001-2000")
        streamer.flush()
        time.sleep(CHUNK_SECONDS)
        rep["phases"]["attack2"] = a2 = streamer.stats("attack2")
        print(line(a2, "attack #2"), flush=True)
        streamer.phase = "after"

        banner(7, "Did it forget the attacks it already knew? (recorded dataset attacks, replayed)")
        rep["forget"] = []
        for c in ("DoS", "PortScan", "DDoS"):
            rr = api(args.server, "/sensor/replay_recorded", {"category": c, "site": "range-forget-check"})
            rep["forget"].append((c, rr["flagged"], rr["replayed"]))
            print(f"  recorded {c}: {rr['flagged']} / {rr['replayed']} still detected", flush=True)
    finally:
        streamer.stop_event.set()
        if not args.keep:
            print("\ntearing down the range...", flush=True)
            teardown()
        streamer.join(timeout=30)
        shutil.rmtree(capdir, ignore_errors=True)

    if streamer.latency:
        rep["latency"] = {"p50": round(statistics.median(streamer.latency), 1), "max": round(max(streamer.latency), 1)}
    rep["chunks"], rep["errors"] = streamer.chunks, streamer.errors
    path = write_report(rep)
    print(f"\nReport saved: {path}")
    if not args.no_open:
        try:
            import webbrowser
            webbrowser.open(path.as_uri())
        except Exception:
            pass
    print("Done. The console's Live sites tab keeps the run (site CYBER-RANGE).")


if __name__ == "__main__":
    main()
