"""Re-capture every screenshot the project guide uses, from the running console.

    python docs/guide/capture.py            # stack running on 127.0.0.1 (scripts/run_stack.ps1)

Drives the installed Edge with Playwright at 1440x900 (phone shots: iPhone 13), dark theme unless stated, and
writes docs/guide/img/*.png. The Live sites shots first replay a recorded DoS window into the 'sandbox' site,
so there is an incident to show; the range report shot uses the newest reports/cyber_range_*.html.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
IMG = Path(__file__).resolve().parent / "img"
BASE = "http://127.0.0.1:8080"


def prefs(theme="dark", ds="cicids2017", compare="0", present="0"):
    return (f"localStorage.setItem('gnnids.helpSeen','1');localStorage.setItem('gnnids.theme','{theme}');"
            f"localStorage.setItem('gnnids.ds','{ds}');localStorage.setItem('gnnids.compare','{compare}');"
            f"localStorage.setItem('gnnids.presentation','{present}');")


def open_page(browser, view, wait=4000, phone=None, **kw):
    ctx = browser.new_context(**(phone or {"viewport": {"width": 1440, "height": 900}}))
    ctx.add_init_script(prefs(**kw))
    page = ctx.new_page()
    page.goto(f"{BASE}/#{view}")
    page.wait_for_timeout(wait)
    return ctx, page


def shot(page, name, full=True, el=None):
    path = IMG / f"{name}.png"
    if el:
        page.locator(el).first.screenshot(path=str(path))
    else:
        page.screenshot(path=str(path), full_page=full)
    print("wrote", path.name)


def main() -> int:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)

        ctx, pg = open_page(b, "overview", 6000)
        shot(pg, "02_overview_full")
        shot(pg, "03_sidebar", el="aside.sidebar")
        shot(pg, "04_topbar", el="header.topbar")
        pg.keyboard.press("Control+k"); pg.wait_for_timeout(400); pg.keyboard.type("incident"); pg.wait_for_timeout(500)
        shot(pg, "81_command_palette", full=False)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        pg.click("#help-btn"); pg.wait_for_timeout(600)
        shot(pg, "80_help_drawer", full=False)
        pg.click("#help-close"); pg.wait_for_timeout(300)
        pg.click("#tour-btn"); pg.wait_for_timeout(800)
        shot(pg, "82_tour", full=False)
        ctx.close()

        ctx, pg = open_page(b, "overview", 6000, present="1")
        shot(pg, "83_presentation_mode", full=False)
        ctx.close()
        ctx, pg = open_page(b, "overview", 6000, theme="light")
        shot(pg, "84_light_theme", full=False)
        ctx.close()
        ctx, pg = open_page(b, "overview", 6000, ds="csecicids2018")
        shot(pg, "85_dataset_2018", full=False)
        ctx.close()

        ctx, pg = open_page(b, "soc", 3000)
        pg.click("#soc-go"); pg.wait_for_timeout(8000)
        pg.locator("#soc-list button, #soc-list [role=option]").first.click(); pg.wait_for_timeout(3000)
        shot(pg, "12_soc_incident_detail")
        ctx.close()

        # Live sites: a recorded DoS window replayed into the sandbox, so there is an incident to show
        ctx, pg = open_page(b, "sites", 3000)
        pg.select_option("#st-replay-cat", "DoS"); pg.click("#st-replay"); pg.wait_for_timeout(9000)
        pg.locator(".site-card", has_text="sandbox").first.click(); pg.wait_for_timeout(5000)
        shot(pg, "72_sites_overview", full=False)
        why = pg.locator("[data-why]").first
        if why.count():
            why.click(); pg.wait_for_timeout(4000)
            pg.locator(".incident").first.scroll_into_view_if_needed()
            shot(pg, "73_sites_incident", el=".incident")
        shot(pg, "74_sites_teach", el="#st-step3")
        ctx.close()

        ctx, pg = open_page(b, "live", 4000)
        shot(pg, "71_live_running")
        ctx.close()

        ctx, pg = open_page(b, "explorer", 7000)
        shot(pg, "20_explorer_graph")
        pg.locator("button", has_text="Model errors").first.click(); pg.wait_for_timeout(3000)
        shot(pg, "21_explorer_model_errors", full=False)
        ctx.close()

        ctx, pg = open_page(b, "classify", 4000)
        pg.click("#cl-run-w"); pg.wait_for_timeout(8000)
        shot(pg, "30_classify_window")
        ctx.close()

        ctx, pg = open_page(b, "models", 6000)
        shot(pg, "40_models_accuracy")
        ctx.close()
        ctx, pg = open_page(b, "models", 6000, compare="1")
        shot(pg, "41_models_compare_on", full=False)
        pg.get_by_role("button", name="Unseen attacks & IP leakage", exact=True).click(); pg.wait_for_timeout(5000)
        ctx.close()
        ctx, pg = open_page(b, "models", 5000)
        pg.get_by_role("button", name="Unseen attacks & IP leakage", exact=True).click(); pg.wait_for_timeout(5000)
        shot(pg, "42_models_unseen")
        ctx.close()

        ctx, pg = open_page(b, "adapt", 6000)
        shot(pg, "50_adapt_drift")
        pg.get_by_role("button", name="Trust: novelty, abstention, alert load", exact=True).click(); pg.wait_for_timeout(5000)
        shot(pg, "51_adapt_trust")
        ctx.close()

        ctx, pg = open_page(b, "repro", 5000)
        shot(pg, "60_repro")
        ctx.close()

        phone = p.devices["iPhone 13"]
        ctx, pg = open_page(b, "overview", 6000, phone=phone)
        shot(pg, "90_phone_overview", full=False)
        pg.click("#menu-btn"); pg.wait_for_timeout(600)
        shot(pg, "91_phone_drawer", full=False)
        ctx.close()

        reports = sorted((ROOT / "reports").glob("cyber_range_*.html"))
        if reports:
            ctx = b.new_context(viewport={"width": 1000, "height": 900})
            pg = ctx.new_page()
            pg.goto(reports[-1].as_uri()); pg.wait_for_timeout(1000)
            shot(pg, "75_range_report")
            ctx.close()
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
