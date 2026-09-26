"""One-shot: is the LinkedIn session actually logged in?

Navigates to /feed (requires login). If it redirects to /authwall or /login,
the session is expired and we must re-login.
"""
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from patchright.sync_api import sync_playwright  # noqa: E402
import linkedin_search as ls  # noqa: E402

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
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=45_000)
        time.sleep(6)
        final_url = page.url
        title = page.title()
        # Logged-in indicators
        body = page.inner_text("body")[:800]
        has_me_menu = page.locator("[data-test-id='me-menu']").count()
        has_authwall = "authwall" in final_url or "checkpoint" in final_url or "login" in final_url
        print("FINAL_URL:", final_url)
        print("TITLE:", title)
        print("HAS_ME_MENU (logged in):", has_me_menu)
        print("HIT_AUTHWALL/CHECKPOINT:", has_authwall)
        print("--- BODY HEAD ---")
        print(body)
    except Exception as exc:
        print("ERROR:", exc.__class__.__name__, exc)
    finally:
        ctx.close()
