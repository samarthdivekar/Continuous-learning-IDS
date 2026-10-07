"""GNN-IDS sensor: capture this machine's network traffic and send it to the central console.

    python sensor/agent.py --list                                   # which interfaces can be captured
    python sensor/agent.py --server http://<central>:8000 --site home-lan --iface 5
    python sensor/agent.py --server http://<central>:8000 --site lab --replay attack.pcap

Live mode runs Wireshark's dumpcap as a ring buffer of short capture files (default 10 s each). Every
finished file is uploaded to POST /sensor/pcap; the central server turns it into CICFlowMeter flows with
the same flow meter the training data came from, scores them and shows them per site. Replay mode sends a
recorded capture the same way, cut into chunks of the same length, so a recorded attack can stand in for a
live one.

Needs: Python 3.10+ (standard library only) and, for live capture, Wireshark with Npcap (dumpcap.exe).
The API key is read from the GNNIDS_API_KEY environment variable and sent in a header, never in the URL.
The sensor never blocks or changes traffic; it only listens.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

DUMPCAP_PATHS = [r"C:\Program Files\Wireshark\dumpcap.exe", "/usr/bin/dumpcap", "/usr/local/bin/dumpcap"]


def find_dumpcap() -> str:
    exe = shutil.which("dumpcap") or next((p for p in DUMPCAP_PATHS if Path(p).exists()), None)
    if not exe:
        sys.exit("dumpcap not found. Install Wireshark (tick 'Install Npcap') from https://www.wireshark.org/ "
                 "and run this again.")
    return exe


def list_interfaces() -> None:
    out = subprocess.run([find_dumpcap(), "-D"], capture_output=True, text=True)
    print(out.stdout or out.stderr)
    print("Pick the number of your Wi-Fi or Ethernet adapter and pass it as --iface.")


# ------------------------------------------------------------------ upload
def upload(server: str, site: str, data: bytes, key: str | None, timeout: float = 300) -> dict:
    req = urllib.request.Request(f"{server.rstrip('/')}/sensor/pcap", data=data, method="POST",
                                 headers={"Content-Type": "application/vnd.tcpdump.pcap", "X-Site": site,
                                          **({"X-API-Key": key} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def report(res: dict, label: str) -> None:
    counts = ", ".join(f"{k} {v}" for k, v in sorted(res.get("counts", {}).items(), key=lambda kv: -kv[1]))
    alert = "  <-- ALERT" if res.get("flagged") else ""
    print(f"[{time.strftime('%H:%M:%S')}] {label}: {res.get('n_flows', 0)} flows"
          f"{f' ({counts})' if counts else ''}; flagged {res.get('flagged', 0)}, "
          f"unfamiliar {res.get('unfamiliar', 0)}{alert}", flush=True)


def send(server: str, site: str, data: bytes, key: str | None, label: str) -> bool:
    try:
        report(upload(server, site, data, key), label)
        return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        print(f"[{time.strftime('%H:%M:%S')}] {label}: server said {exc.code}: {detail}", flush=True)
        if exc.code in (401, 403):
            sys.exit("API key rejected: set GNNIDS_API_KEY to the key the central server uses.")
        return exc.code < 500                     # a 4xx will not get better on retry
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        print(f"[{time.strftime('%H:%M:%S')}] {label}: cannot reach {server} ({exc}); will retry", flush=True)
        return False


# ------------------------------------------------------------------ live capture
def server_filter(server: str) -> str:
    """Capture filter that leaves out this sensor's own uploads, so they are not scored as traffic."""
    u = urlparse(server)
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        ip = socket.gethostbyname(u.hostname)
    except OSError:
        return ""
    return f"not (host {ip} and tcp port {port})"


def live(args, key: str | None) -> None:
    spool = Path(tempfile.mkdtemp(prefix="gnnids_sensor_"))
    filt = " and ".join(f"({f})" for f in (server_filter(args.server), args.filter) if f)
    cmd = [find_dumpcap(), "-i", str(args.iface), "-P", "-q", "-b", f"duration:{args.chunk}", "-b", "files:60",
           "-w", str(spool / "chunk.pcap")] + (["-f", filt] if filt else [])
    print(f"site '{args.site}' -> {args.server}; capturing interface {args.iface} in {args.chunk}s chunks")
    if filt:
        print(f"capture filter: {filt}")
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    try:
        while True:
            time.sleep(1)
            if proc.poll() is not None:
                sys.exit(f"dumpcap stopped: {(proc.stderr.read() or '').strip()[:500]}\n"
                         "On Windows, Npcap must be installed and the interface number must exist (--list).")
            files = sorted(spool.glob("chunk_*.pcap"))
            for f in files[:-1]:                  # the newest file is still being written
                if send(args.server, args.site, f.read_bytes(), key, f.name.split("_")[-1].split(".")[0]):
                    f.unlink(missing_ok=True)
    except KeyboardInterrupt:
        print("stopping")
    finally:
        proc.terminate()
        shutil.rmtree(spool, ignore_errors=True)


# ------------------------------------------------------------------ replay
def split_pcap(path: Path, seconds: float):
    """Yield classic-pcap byte chunks of `seconds` of capture time each (standard library only)."""
    raw = path.read_bytes()
    if len(raw) < 24:
        sys.exit(f"{path} is too short to be a capture")
    magic = raw[:4]
    if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        end, nano = "<", magic == b"\x4d\x3c\xb2\xa1"
    elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
        end, nano = ">", magic == b"\xa1\xb2\x3c\x4d"
    else:
        sys.exit(f"{path} is not a classic pcap file (pcapng?). Convert it first: "
                 f"editcap -F pcap {path.name} {path.stem}.pcap")
    header, pos, chunk, start = raw[:24], 24, [], None
    div = 1e9 if nano else 1e6
    while pos + 16 <= len(raw):
        sec, frac, incl, _ = struct.unpack(end + "IIII", raw[pos:pos + 16])
        rec = raw[pos:pos + 16 + incl]
        pos += 16 + incl
        t = sec + frac / div
        if start is None:
            start = t
        if t - start >= seconds and chunk:
            yield header + b"".join(chunk)
            chunk, start = [], t
        chunk.append(rec)
    if chunk:
        yield header + b"".join(chunk)


def replay(args, key: str | None) -> None:
    path = Path(args.replay)
    chunks = list(split_pcap(path, args.chunk))
    print(f"replaying {path.name} to {args.server} as site '{args.site}': {len(chunks)} chunks of {args.chunk}s")
    for i, data in enumerate(chunks, 1):
        for attempt in range(5):
            if send(args.server, args.site, data, key, f"chunk {i}/{len(chunks)}"):
                break
            time.sleep(5)
        else:
            sys.exit("giving up: the server keeps failing (see its log)")
        if not args.fast and i < len(chunks):
            time.sleep(args.chunk)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="list capture interfaces and exit")
    p.add_argument("--server", help="central API, e.g. http://100.101.102.103:8000")
    p.add_argument("--site", help="name shown in the console, e.g. home-lan or campus")
    p.add_argument("--iface", help="interface number or name from --list")
    p.add_argument("--replay", help="send a recorded .pcap instead of capturing live")
    p.add_argument("--chunk", type=float, default=10.0, help="seconds per capture chunk (default 10)")
    p.add_argument("--filter", default="", help="extra capture filter (BPF), e.g. 'not port 53'")
    p.add_argument("--fast", action="store_true", help="replay without waiting between chunks")
    args = p.parse_args()
    if args.list:
        return list_interfaces()
    if not args.server or not args.site:
        p.error("--server and --site are required")
    key = os.environ.get("GNNIDS_API_KEY")
    if args.replay:
        return replay(args, key)
    if not args.iface:
        p.error("give --iface (see --list) or --replay")
    live(args, key)


if __name__ == "__main__":
    main()
