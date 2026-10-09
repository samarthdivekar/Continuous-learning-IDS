"""Measure the model's false-alarm rate on YOUR OWN benign traffic, before and after teaching it.

    # capture ~10 minutes of normal use first (do nothing unusual), then:
    python sensor/measure_fpr.py --pcap my_normal_traffic.pcap --server http://127.0.0.1:8000
    # or from a flow CSV the pinned CICFlowMeter already produced:
    python sensor/measure_fpr.py --csv flows.csv --server http://127.0.0.1:8000

This is the honest version of "does teaching reduce false alarms?": the flows are split into a teach half
and a held-out half; the server measures the false-positive rate on the held-out half, teaches the teach
half as benign, measures the held-out half again, and then restores the model (so this changes nothing —
it only measures). It also reports what teaching did to the model's recall on the attacks it already knew,
because teaching on benign-only traffic could trade attack detection for fewer false alarms.

Run it on traffic you are sure is benign; the number is only meaningful for the network you captured on,
and does not go into the project's results. Converting the capture needs Docker and the flow-meter image
(see docs/LIVE_DEMO.md); run this on the machine that has them (usually the central one).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.live.flowmeter import FlowMeterError, pcap_to_flows, read_flow_csv  # noqa: E402


def post(server: str, path: str, body: dict, key: str | None, timeout: float = 900) -> dict:
    req = urllib.request.Request(f"{server.rstrip('/')}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **({"X-API-Key": key} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--pcap", type=Path, help="a capture of your own benign traffic")
    src.add_argument("--csv", type=Path, help="a CICFlowMeter flow CSV (from the pinned meter) instead")
    p.add_argument("--server", default="http://127.0.0.1:8000")
    p.add_argument("--teach-fraction", type=float, default=0.5, help="share taught; the rest is held out (default 0.5)")
    p.add_argument("--epochs", type=int, default=None)
    args = p.parse_args()

    try:
        flows = read_flow_csv(args.csv) if args.csv else pcap_to_flows(args.pcap)
    except FlowMeterError as exc:
        sys.exit(f"flow meter: {exc}")
    if len(flows) < 4:
        sys.exit(f"only {len(flows)} flows; capture more traffic (a few minutes of normal use).")
    print(f"{len(flows)} benign flows -> {args.server}; measuring (teach {args.teach_fraction:.0%}, hold out the rest)...")

    body = {"flows": flows, "teach_fraction": args.teach_fraction, "epochs": args.epochs}
    try:
        r = post(args.server, "/live/fpr_study", body, os.environ.get("GNNIDS_API_KEY"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"server {exc.code}: {exc.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as exc:
        sys.exit(f"cannot reach {args.server}: {exc}")

    print(f"""
held-out benign flows: {r['n_holdout']}   (taught on {r['n_teach']})

false alarms on your benign traffic
  before teaching : {r['fpr_before'] * 100:6.2f}%   ({r['flagged_before']} of {r['n_holdout']} flows flagged)
  after teaching  : {r['fpr_after'] * 100:6.2f}%   ({r['flagged_after']} of {r['n_holdout']} flows flagged)

the cost (recall on attacks the model already knew, from the training test set)
  before teaching : {r['old_attack_f1_before']:.3f} macro-F1
  after teaching  : {r['old_attack_f1_after']:.3f} macro-F1

the model was restored afterwards - this only measured, it changed nothing.""")
    if r["fpr_before"] == 0:
        print("note: no false alarms even before teaching on this capture - try a longer or busier capture.")


if __name__ == "__main__":
    main()
