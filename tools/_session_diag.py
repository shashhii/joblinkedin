"""One-shot: open LinkedIn with the restored session and report where it lands.

Distinguishes:
  - AUTHWALL  -> session expired, need to re-login
  - CHECKPOINT-> LinkedIn security check (CAPTCHA / verify identity)
  - LOGGED-IN -> session valid; 0 jobs would then be genuine throttling
"""
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from patchright.sync_api import sync_playwright  # noqa: E402
import linkedin_search as ls  # noqa: E402

URL = ("https://www.linkedin.com/jobs/search/?"
       "keywords=python+developer&location=India&f_E=1%2C2%2C3"
       "&f_AL=true&f_TPR=r604800&sortBy=DD&start=0")

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(ls.PROFILE_DIR),
        headless=True,
        no_viewport=True,
        args=ls.BROWSER_ARGS,
    )
    ls._inject_session(ctx)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=45_000)
        time.sleep(6)
        final_url = page.url
        title = page.title()
        body = page.inner_text("body")[:1500]
        cards = page.locator("a[href*='/jobs/view/']").count()
        print("FINAL_URL:", final_url)
        print("TITLE:", title)
        print("JOB_CARDS:", cards)
        print("--- BODY HEAD ---")
        print(body)
        # Save a screenshot for the record
        shot = HERE / ".linkedin_debug" / "diag_session.png"
        shot.parent.mkdir(exist_ok=True)
        page.screenshot(path=str(shot))
        print("SCREENSHOT:", shot)
    except Exception as exc:
        print("ERROR:", exc.__class__.__name__, exc)
    finally:
        ctx.close()
