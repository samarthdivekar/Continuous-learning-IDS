"""Packet capture -> flow records with exactly the training data's features.

The models read CICFlowMeter flow records, so live packets go through the same corrected CICFlowMeter
(GintsEngelen/CICFlowMeter, pinned in sensor/cicflowmeter.Dockerfile) that produced the improved
CIC-IDS2017 / CSE-CIC-IDS2018 releases. Its CSV header must equal the training data's column for column;
a different flow meter, or a newer commit of this one, is refused rather than scored, because a model fed
differently computed features gives confident answers that mean nothing.
"""
from __future__ import annotations

import csv
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

IMAGE = os.environ.get("GNNIDS_FLOWMETER_IMAGE", "gnnids-cicflowmeter")

# Header of the improved CIC-IDS2017 / CSE-CIC-IDS2018 CSVs without their "id" and "Attempted Category"
# columns, which is what the pinned flow meter writes.
EXPECTED_HEADER = [
    "Flow ID", "Src IP", "Src Port", "Dst IP", "Dst Port", "Protocol", "Timestamp", "Flow Duration",
    "Total Fwd Packet", "Total Bwd packets", "Total Length of Fwd Packet", "Total Length of Bwd Packet",
    "Fwd Packet Length Max", "Fwd Packet Length Min", "Fwd Packet Length Mean", "Fwd Packet Length Std",
    "Bwd Packet Length Max", "Bwd Packet Length Min", "Bwd Packet Length Mean", "Bwd Packet Length Std",
    "Flow Bytes/s", "Flow Packets/s", "Flow IAT Mean", "Flow IAT Std", "Flow IAT Max", "Flow IAT Min",
    "Fwd IAT Total", "Fwd IAT Mean", "Fwd IAT Std", "Fwd IAT Max", "Fwd IAT Min", "Bwd IAT Total",
    "Bwd IAT Mean", "Bwd IAT Std", "Bwd IAT Max", "Bwd IAT Min", "Fwd PSH Flags", "Bwd PSH Flags",
    "Fwd URG Flags", "Bwd URG Flags", "Fwd RST Flags", "Bwd RST Flags", "Fwd Header Length",
    "Bwd Header Length", "Fwd Packets/s", "Bwd Packets/s", "Packet Length Min", "Packet Length Max",
    "Packet Length Mean", "Packet Length Std", "Packet Length Variance", "FIN Flag Count", "SYN Flag Count",
    "RST Flag Count", "PSH Flag Count", "ACK Flag Count", "URG Flag Count", "CWR Flag Count", "ECE Flag Count",
    "Down/Up Ratio", "Average Packet Size", "Fwd Segment Size Avg", "Bwd Segment Size Avg",
    "Fwd Bytes/Bulk Avg", "Fwd Packet/Bulk Avg", "Fwd Bulk Rate Avg", "Bwd Bytes/Bulk Avg",
    "Bwd Packet/Bulk Avg", "Bwd Bulk Rate Avg", "Subflow Fwd Packets", "Subflow Fwd Bytes",
    "Subflow Bwd Packets", "Subflow Bwd Bytes", "FWD Init Win Bytes", "Bwd Init Win Bytes",
    "Fwd Act Data Pkts", "Fwd Seg Size Min", "Active Mean", "Active Std", "Active Max", "Active Min",
    "Idle Mean", "Idle Std", "Idle Max", "Idle Min", "ICMP Code", "ICMP Type", "Total TCP Flow Time", "Label",
]
# Identity columns: they define the graph and the incident, never a model feature.
NOT_FEATURES = {"Flow ID", "Src IP", "Src Port", "Dst IP", "Timestamp", "Label"}


class FlowMeterError(RuntimeError):
    pass


def check_header(header: list[str]) -> None:
    got = [h.strip() for h in header]
    if got != EXPECTED_HEADER:
        missing = [c for c in EXPECTED_HEADER if c not in got]
        extra = [c for c in got if c not in EXPECTED_HEADER]
        raise FlowMeterError(
            "flow CSV does not come from the pinned CICFlowMeter (columns differ from the training data"
            + (f"; missing {missing[:6]}" if missing else "") + (f"; unexpected {extra[:6]}" if extra else "")
            + ("; same columns in a different order" if not missing and not extra else "") + ")")


def read_flow_csv(path: Path) -> list[dict]:
    """CICFlowMeter CSV -> flow dicts {ts, src_ip, dst_ip, src_port, dst_port, protocol, features}."""
    flows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return []
        check_header(header)
        for row in reader:
            if len(row) != len(EXPECTED_HEADER):
                continue                                   # truncated last line of an interrupted run
            rec = dict(zip(EXPECTED_HEADER, row))
            feats = {}
            for k, v in rec.items():
                if k in NOT_FEATURES:
                    continue
                try:
                    x = float(v)
                except ValueError:
                    x = float("nan")
                # NaN / Infinity (rates of zero-duration flows) -> 0, exactly as training cleaned them
                # (src/preprocessing/clean.py); it also keeps the flows valid JSON
                feats[k] = x if math.isfinite(x) else 0.0
            flows.append({"ts": rec["Timestamp"].replace(" ", "T") + "+00:00", "src_ip": rec["Src IP"],
                          "dst_ip": rec["Dst IP"], "src_port": int(float(rec["Src Port"] or 0)),
                          "dst_port": int(float(rec["Dst Port"] or 0)), "protocol": int(float(rec["Protocol"] or 0)),
                          "features": feats})
    return flows


def docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker is not installed"
    r = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True, text=True)
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()
        if msg and "daemon" in msg[-1].lower():
            return False, "Docker Desktop is not running"
        return False, (f"flow-meter image '{IMAGE}' not built: docker build -t {IMAGE} "
                       f"-f sensor/cicflowmeter.Dockerfile sensor")
    return True, "ok"


def pcap_to_flows(pcap: Path, timeout: float = 300) -> list[dict]:
    """Convert one capture with the pinned flow meter (in Docker) and return its flows."""
    ok, why = docker_available()
    if not ok:
        raise FlowMeterError(why)
    with tempfile.TemporaryDirectory(prefix="gnnids_fm_") as tmp:
        tmp = Path(tmp)
        (tmp / "in").mkdir()
        (tmp / "out").mkdir()                              # cfm writes nothing if the folder is missing
        shutil.copy(pcap, tmp / "in" / "capture.pcap")
        cmd = ["docker", "run", "--rm", "--network", "none", "-v", f"{tmp}:/data", IMAGE, "/data/in", "/data/out"]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "MSYS_NO_PATHCONV": "1"})
        produced = sorted((tmp / "out").glob("*.csv"))
        if r.returncode != 0 or not produced:
            tail = " ".join((r.stdout + r.stderr).strip().splitlines()[-3:])
            raise FlowMeterError(f"flow meter failed (exit {r.returncode}): {tail[:300]}")
        return read_flow_csv(produced[0])
