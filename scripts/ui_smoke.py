"""Console smoke test: every page loads, in every layout, without a console error.

    python scripts/ui_smoke.py                       # against the running stack on :8080
    python scripts/ui_smoke.py --expect-ml down      # assert the model service is down (degraded mode)

Needs the stack running (scripts/run_stack.ps1) and Playwright (`pip install playwright`). It drives
the Edge already installed on Windows (channel "msedge"); elsewhere pass --browser chromium after
`python -m playwright install chromium`.

For every page and sub-page, at desktop width (1440 px) and phone width (iPhone 13), in dark and in
light theme, it fails when:
  * the page raises an uncaught JavaScript error;
  * the console logs an error that is not a failed HTTP request with an expected status (503 when the
    model service is down; 404 for an experiment that has not been run, which the page shows as
    "not run yet");
  * the page is still showing its loading placeholder after the timeout;
  * the document is wider than the viewport (horizontal scroll on a phone).
It also checks the sidebar reports the model service in the state --expect-ml asks for.
"""
from __future__ import annotations

import argparse
import re
import sys

from playwright.sync_api import sync_playwright

PAGES = {
    "overview": [], "soc": [], "live": [], "explorer": [], "classify": [],
    "models": ["Accuracy & forgetting", "Unseen attacks & IP leakage"],
    "adapt": ["Drift & retraining", "Trust: novelty, abstention, alert load"],
    "repro": [],
}


def check_page(page, view: str, sub: str | None, ml_down: bool, errors: list, timeout_ms: int) -> list[str]:
    errors.clear()
    page.goto(f"{BASE}/#{view}")
    page.wait_for_load_state("domcontentloaded")
    if sub:
        page.get_by_role("button", name=sub, exact=True).click()
    page.wait_for_timeout(timeout_ms)
    problems = []
    allowed = {404, 503} if ml_down else {404}
    for kind, text, status in errors:
        if kind == "pageerror":
            problems.append(f"uncaught error: {text}")
        elif status is None or status not in allowed:
            problems.append(f"console error: {text}" + (f" (HTTP {status})" if status else ""))
    section = page.locator(f"#view-{view}")
    if section.inner_text().strip() in ("", "Loading…"):
        problems.append("page still loading or empty")
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    if overflow > 1:
        problems.append(f"document {overflow}px wider than the viewport")
    return problems


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--expect-ml", choices=["up", "down", "auto"], default="auto")
    ap.add_argument("--browser", choices=["msedge", "chromium"], default="msedge")
    ap.add_argument("--wait", type=int, default=3500, help="ms to let a page settle")
    args = ap.parse_args()
    BASE = args.base.rstrip("/")
    failures, checked = [], 0
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=None if args.browser == "chromium" else "msedge", headless=True)
        layouts = {"desktop": {"viewport": {"width": 1440, "height": 900}}, "phone": p.devices["iPhone 13"]}
        for layout, opts in layouts.items():
            for theme in ("dark", "light"):
                ctx = browser.new_context(**opts)
                ctx.add_init_script(f"localStorage.setItem('gnnids.helpSeen','1');"
                                    f"localStorage.setItem('gnnids.theme','{theme}');")
                page = ctx.new_page()
                errors: list = []
                page.on("pageerror", lambda e: errors.append(("pageerror", str(e), None)))

                def on_console(msg):
                    if msg.type != "error" or "net::ERR_" in msg.text:   # network failures: see requestfailed
                        return
                    m = re.search(r"status of (\d{3})", msg.text)
                    errors.append(("console", msg.text, int(m.group(1)) if m else None))
                page.on("console", on_console)
                page.on("requestfailed", lambda r: errors.append(
                    ("console", f"request failed: {r.url.replace(BASE, '')} ({r.failure})", None)))

                page.goto(f"{BASE}/#overview")
                page.wait_for_timeout(2500)
                ml_state = page.locator("#pill-ml .status-val").inner_text().strip()
                ml_down = ml_state != "online"
                if args.expect_ml != "auto" and ml_down != (args.expect_ml == "down"):
                    failures.append(f"[{layout}/{theme}] model service is '{ml_state}', expected {args.expect_ml}")
                for view, subs in PAGES.items():
                    for sub in (subs or [None]):
                        if layout == "phone":                    # sub-tabs are reached the same way on a phone
                            page.evaluate("document.body.classList.remove('nav-open')")
                        probs = check_page(page, view, sub, ml_down, errors, args.wait)
                        checked += 1
                        where = f"[{layout}/{theme}] {view}{' › ' + sub if sub else ''}"
                        failures += [f"{where}: {x}" for x in probs]
                        print(f"{'FAIL' if probs else 'ok  '} {where}")
                ctx.close()
        browser.close()
    print(f"\n{checked} page loads checked, model service {'down' if ml_down else 'up'}; {len(failures)} problem(s)")
    for f in failures:
        print("  -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
