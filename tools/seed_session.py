"""One-time session seeder: export the local LinkedIn login and push to R2.

Run this ONCE on your local machine (where the browser profile is already
logged in) before deploying to Render:

    python tools/seed_session.py

It opens the persistent profile headless, loads a LinkedIn page to confirm
the session is alive, exports all cookies to tools/.session/cookies.json,
and uploads cookies + progress state to R2.

Requires R2_* env vars (or a local .env file) to be set.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import r2_sync  # noqa: E402

PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"

BROWSER_ARGS = [
    "--start-maximized",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--no-first-run",
    "--no-default-browser-check",
]


def main() -> int:
    if not r2_sync.configured():
        print("R2 not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
              "R2_SECRET_ACCESS_KEY, R2_BUCKET (env vars or .env).")
        return 1

    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            no_viewport=True,
            args=BROWSER_ARGS,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto("https://www.linkedin.com/feed/",
                      wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(4000)
            url = page.url
            if "authwall" in url or "/login" in url:
                print("SESSION NOT LOGGED IN: LinkedIn redirected to the "
                      "authwall. Log in once with --headed first, then re-run.")
                return 1
            print(f"session alive: {url}")
            n = r2_sync.export_cookies_from_context(context)
            print(f"exported {n} cookies -> {r2_sync.COOKIES_FILE}")
        finally:
            context.close()

    ok = r2_sync.upload_session()
    if ok:
        print("SEED_OK: session + state uploaded to R2. Ready to deploy.")
        return 0
    print("SEED_FAILED: local export worked but R2 upload failed.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
