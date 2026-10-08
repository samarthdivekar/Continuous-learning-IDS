"""Generate sample flow CSVs you can upload on the Classify tab.

    python scripts/make_sample_csvs.py

Writes 10 CSVs under sample_flows/, each a real held-out window from CIC-IDS2017 with the full
CICFlowMeter feature set in RAW units (the parquet stores scaled features, so they are inverse-transformed
back; the Classify tab re-scales them exactly as it does a live capture). src_ip / dst_ip are included so
the graph can be built; a Label column is included for your reference and is ignored by the classifier.
"""
from __future__ import annotations

import csv
import glob
import os
from pathlib import Path

import sys
import numpy as np
import pyarrow.dataset as ds
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.preprocessing.scaling import FeatureScaler

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "sample_flows"


def latest_processed() -> Path:
    dirs = sorted(glob.glob(str(ROOT / "data" / "processed" / "cicids2017_*")), key=os.path.getmtime)
    if not dirs:
        raise SystemExit("no processed CIC-IDS2017 data found (run experiments.prepare_data first)")
    return Path(dirs[-1])


def main() -> None:
    OUT.mkdir(exist_ok=True)
    proc = latest_processed()
    scaler = FeatureScaler.load(proc / "scaler.json")
    cols = list(scaler.columns)
    table = ds.dataset(proc / "flows.parquet").to_table(
        columns=["category", "split", "src_ip", "dst_ip", *cols]).to_pandas()
    test = table[table["split"] == 2]

    def window_for(category: str, max_rows: int = 1500):
        """A test slice rich in `category` (or benign for 'Benign'), inverse-transformed to raw units."""
        if category == "Benign":
            sel = test[test["category"] == "Benign"].head(max_rows)
        else:
            sel = test[test["category"].str.lower() == category.lower()]
            # pad with benign context so the graph looks like a real window, attack first
            benign = test[test["category"] == "Benign"].head(max_rows - min(len(sel), max_rows // 2))
            sel = sel.head(max_rows // 2)
            import pandas as pd
            sel = pd.concat([sel, benign]).head(max_rows)
        if sel.empty:
            return None
        raw = scaler.inverse_transform(sel[cols].to_numpy())
        return sel["src_ip"].to_numpy(), sel["dst_ip"].to_numpy(), sel["category"].to_numpy(), raw

    def write(name: str, category: str):
        got = window_for(category)
        if got is None:
            print(f"  skip {name}: no flows for {category}")
            return 0
        src, dst, cat, raw = got
        path = OUT / name
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["src_ip", "dst_ip", *cols, "Label"])
            for i in range(len(src)):
                w.writerow([src[i], dst[i], *[f"{v:.6g}" if np.isfinite(v) else 0 for v in raw[i]], cat[i]])
        print(f"  wrote {name}: {len(src)} flows")
        return len(src)

    jobs = [
        ("01_benign_traffic.csv", "Benign"),
        ("02_dos_attack.csv", "DoS"),
        ("03_portscan_attack.csv", "PortScan"),
        ("04_ddos_attack.csv", "DDoS"),
        ("05_bruteforce_attack.csv", "BruteForce"),
        ("06_infiltration_attack.csv", "Infiltration"),
        ("07_botnet_attack.csv", "Botnet"),
        ("08_webattack_attack.csv", "WebAttack"),
    ]
    print(f"writing sample CSVs to {OUT} ...")
    for name, cat in jobs:
        write(name, cat)

    # 09: a mix of several attacks in one window
    import pandas as pd
    parts = []
    for c in ("DoS", "PortScan", "DDoS", "BruteForce"):
        parts.append(test[test["category"].str.lower() == c.lower()].head(300))
    parts.append(test[test["category"] == "Benign"].head(600))
    mix = pd.concat(parts)
    raw = scaler.inverse_transform(mix[cols].to_numpy())
    with open(OUT / "09_mixed_attacks.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["src_ip", "dst_ip", *cols, "Label"])
        for i in range(len(mix)):
            w.writerow([mix["src_ip"].iloc[i], mix["dst_ip"].iloc[i],
                        *[f"{v:.6g}" if np.isfinite(v) else 0 for v in raw[i]], mix["category"].iloc[i]])
    print(f"  wrote 09_mixed_attacks.csv: {len(mix)} flows")

    # 10: a real nmap scan captured in the cyber-range sandbox, if present (tests a real live capture)
    nmap = ROOT / "sensor" / "_lab" / "nmap_scan.pcap"
    if nmap.exists():
        try:
            from src.live.flowmeter import pcap_to_flows
            flows = pcap_to_flows(nmap)
            feat_cols = list(flows[0]["features"].keys()) if flows else []
            with open(OUT / "10_nmap_scan_live.csv", "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["src_ip", "dst_ip", *feat_cols])
                for f in flows:
                    w.writerow([f["src_ip"], f["dst_ip"], *[f["features"][c] for c in feat_cols]])
            print(f"  wrote 10_nmap_scan_live.csv: {len(flows)} flows (real captured scan)")
        except Exception as exc:
            print(f"  skip 10_nmap_scan_live.csv: {exc}")
    else:
        print("  skip 10_nmap_scan_live.csv: no nmap capture at sensor/_lab/nmap_scan.pcap")

    print(f"\nDone. Upload any of these on the Classify tab ({OUT}).")


if __name__ == "__main__":
    main()
