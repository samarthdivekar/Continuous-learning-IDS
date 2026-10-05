"""Feed a packet capture into the running system.

    python scripts/pcap_to_flows.py capture.pcap --api http://localhost:8000

The model consumes CICFlowMeter-style *flow* records, not raw packets, so a capture
has to be converted first. This script does not reimplement that conversion: it drives
the reference tool (CICFlowMeter) when it is available and otherwise tells you exactly
what to install. Flows that come out are posted to /ingest and classified by /predict,
the same path the dashboard's Classify tab uses.

CICFlowMeter: https://github.com/ahlashkari/CICFlowMeter (Java 8+, `CICFlowMeter.jar`).
Point to it with --jar or the CICFLOWMETER_JAR environment variable. If you already have
a flow CSV from any tool, skip conversion with --csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

IP_COLUMNS = {"src": ("src_ip", "source ip", "src ip", "srcip"),
              "dst": ("dst_ip", "destination ip", "dst ip", "dstip"),
              "ts": ("timestamp", "ts", "flow start")}
SKIP = {"flow id", "label", "protocol_name"}


def convert(pcap: Path, jar: Path | None, out_dir: Path) -> Path:
    """pcap -> flow CSV via CICFlowMeter. Returns the CSV path."""
    if jar is None or not jar.exists():
        sys.exit("No CICFlowMeter jar found. Install it from https://github.com/ahlashkari/CICFlowMeter\n"
                 "then re-run with --jar <path to CICFlowMeter.jar>, or pass an existing flow CSV with --csv.")
    if shutil.which("java") is None:
        sys.exit("Java is required to run CICFlowMeter (java not found on PATH).")
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"converting {pcap.name} with CICFlowMeter ...")
    subprocess.run(["java", "-jar", str(jar), str(pcap), str(out_dir)], check=True)
    produced = sorted(out_dir.glob("*.csv"))
    if not produced:
        sys.exit(f"CICFlowMeter produced no CSV in {out_dir}")
    return produced[0]


def read_flows(csv_path: Path, limit: int) -> list[dict]:
    """Flow CSV -> the /ingest payload shape, keeping every numeric column as a feature."""
    flows = []
    with open(csv_path, newline="", encoding="utf-8", errors="replace") as fh:
        for row in csv.DictReader(fh):
            lower = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            pick = lambda names: next((lower[n] for n in names if lower.get(n)), None)  # noqa: E731
            src, dst = pick(IP_COLUMNS["src"]), pick(IP_COLUMNS["dst"])
            if not src or not dst:
                sys.exit(f"{csv_path.name} has no source/destination IP columns; is it a flow CSV?")
            features = {}
            for key, value in row.items():
                name = (key or "").strip()
                if not name or name.lower() in SKIP or name.lower() in sum(IP_COLUMNS.values(), ()):
                    continue
                try:
                    features[name] = float(value)
                except (TypeError, ValueError):
                    continue
            flows.append({"ts": pick(IP_COLUMNS["ts"]) or "1970-01-01T00:00:00",
                          "src_ip": src, "dst_ip": dst, "features": features})
            if len(flows) >= limit:
                break
    return flows


def post(api: str, path: str, body: dict, key: str | None) -> dict:
    req = urllib.request.Request(f"{api.rstrip('/')}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"X-API-Key": key} if key else {})})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pcap", nargs="?", type=Path, help="capture file (.pcap/.pcapng)")
    p.add_argument("--csv", type=Path, help="skip conversion: an existing CICFlowMeter-style flow CSV")
    p.add_argument("--jar", type=Path, default=os.environ.get("CICFLOWMETER_JAR"), help="path to CICFlowMeter.jar")
    p.add_argument("--api", default="http://localhost:8000", help="API base URL")
    p.add_argument("--api-key", default=os.environ.get("GNNIDS_API_KEY"))
    p.add_argument("--limit", type=int, default=5000, help="max flows to send (default 5000)")
    p.add_argument("--model", default="gnn_ewc_replay")
    args = p.parse_args()

    if not args.csv and not args.pcap:
        p.error("give a pcap file, or --csv with an existing flow CSV")
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = args.csv or convert(args.pcap, Path(args.jar) if args.jar else None, Path(tmp))
        flows = read_flows(Path(csv_path), args.limit)
        if not flows:
            sys.exit("no flows found in the CSV")
        print(f"{len(flows)} flows -> {args.api}")
        ingested = post(args.api, "/ingest", {"flows": flows}, args.api_key)
        result = post(args.api, "/predict", {"flow_ids": ingested["flow_ids"], "models": [args.model]}, args.api_key)

    counts = result["models"][args.model]["counts"]
    print(f"\n{result['n_flows']} flows between {result['n_nodes']} hosts, classified by {args.model}:")
    for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {label:<14} {n:>7,}")
    for warning in result.get("warnings", []):
        print(f"note: {warning}")
    print(f"\nOpen the dashboard to inspect them: {args.api.replace(':8000', ':8080')}/#soc")


if __name__ == "__main__":
    main()
