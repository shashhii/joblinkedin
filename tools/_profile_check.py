"""One-shot: check the profile's OWN session (NO cookie injection).

If this shows logged-in but the injected version doesn't, then
_inject_session() is clobbering the valid profile session with stale R2
cookies — and the fix is to skip injection when the profile is already
logged in.
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
    # NOTE: deliberately NOT calling ls._inject_session(ctx)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    try:
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=45_000)
        time.sleep(6)
        final_url = page.url
        me_menu = page.locator("[data-test-id='me-menu']").count()
        print("FINAL_URL:", final_url)
        print("HAS_ME_MENU (logged in):", me_menu)
        # Show the li_at cookie the profile itself holds
        for c in ctx.cookies("https://www.linkedin.com"):
            if c["name"] in ("li_at", "JSESSIONID"):
                exp = c.get("expires", -1)
                import datetime
                exp_s = datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M") if exp > 0 else "session"
                print(f"COOKIE {c['name']}: len={len(c['value'])}, expires={exp_s}")
    except Exception as exc:
        print("ERROR:", exc.__class__.__name__, exc)
    finally:
        ctx.close()
