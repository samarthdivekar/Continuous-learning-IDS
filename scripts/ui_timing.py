"""Measure how long each console tab takes to show its content, and which API calls are slow.

    python scripts/ui_timing.py            # stack must be running (scripts/run_stack.ps1)

For every tab: time from navigation until no loading placeholder is left and the network is idle, plus the
slowest /api requests made while it loaded. Writes nothing; prints a table.
"""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
VIEWS = ["overview", "soc", "live", "sites", "explorer", "classify", "models", "adapt", "repro"]
LOADING = "text=/^\\s*Loading/i"


def main() -> int:
    rows = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)  # Edge ships with Windows, as in ui_smoke.py
        page = b.new_page(viewport={"width": 1440, "height": 900})
        timings: dict[str, float] = {}
        page.on("requestfinished", lambda r: timings.__setitem__(
            r.url, r.timing["responseEnd"]) if "/api/" in r.url else None)
        page.goto(f"{BASE}/#overview")
        page.wait_for_load_state("networkidle")
        for rnd in range(2):                       # round 0 = first visit, round 1 = revisit (cached)
            for v in VIEWS:
                timings.clear()
                t0 = time.perf_counter()
                page.goto(f"{BASE}/#{v}")
                try:
                    page.wait_for_load_state("networkidle", timeout=30000)
                    page.wait_for_function(
                        "() => !Array.from(document.querySelectorAll('main *')).some(e => e.children.length === 0 && /^\\s*Loading/i.test(e.textContent || ''))",
                        timeout=30000)
                except Exception as exc:  # noqa: BLE001
                    rows.append((rnd, v, -1.0, f"timeout: {exc.__class__.__name__}"))
                    continue
                dt = time.perf_counter() - t0
                slow = sorted(timings.items(), key=lambda kv: -kv[1])[:2]
                rows.append((rnd, v, dt, ", ".join(f"{u.split('/api/')[-1][:60]} {ms:.0f}ms" for u, ms in slow)))
        b.close()
    print(f"{'visit':6}{'tab':10}{'seconds':>8}  slowest api calls")
    for rnd, v, dt, s in rows:
        print(f"{['first', 'again'][rnd]:6}{v:10}{dt:8.2f}  {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
