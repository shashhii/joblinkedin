"""Open LinkedIn job pages in a VISIBLE browser using the saved session.

Usage:
    python tools/open_job.py <job-url> [more-urls ...]

The browser reuses ~/.linkedin-mcp/profile (already logged in), so you land
on the job page authenticated. Review the posting, click Easy Apply / Apply,
complete any final steps, and submit yourself — by design this script never
clicks submit (human-in-the-loop, same guarantee as career-ops).

The window stays open until you close it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"


def main() -> int:
    urls = sys.argv[1:]
    if not urls:
        print("usage: python tools/open_job.py <job-url> [more-urls ...]", flush=True)
        return 2

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        for i, url in enumerate(urls):
            target = page if i == 0 else context.new_page()
            try:
                target.goto(url, wait_until="domcontentloaded", timeout=60_000)
                print(f"[open] {url}", flush=True)
            except Exception as exc:
                print(f"[open] failed {url}: {exc.__class__.__name__}", flush=True)

        print(
            "[open] Browser left open. Review and submit applications yourself; "
            "close the window when done.",
            flush=True,
        )
        try:
            while context.pages:
                time.sleep(5)
        except KeyboardInterrupt:
            pass
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
