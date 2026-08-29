"""Load a job page and dump the apply-button area to see its current state."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DEBUG_DIR = HERE / ".apply_debug"
PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"

DUMP_JS = """
() => {
  let out = 'URL: ' + location.href + '\\n\\n';
  const btns = document.querySelectorAll('button');
  out += '=== BUTTONS (first 40) ===\\n';
  let n = 0;
  btns.forEach((b) => {
    if (n++ >= 40) return;
    const t = (b.innerText || '').trim().replace(/\\n/g, ' ');
    if (t) out += 'BTN: ' + t.slice(0, 80) + ' | visible=' + (b.offsetParent !== null) + '\\n';
  });
  out += '\\n=== BODY HEAD ===\\n' + (document.body.innerText || '').slice(0, 800);
  return out;
}
"""


def main() -> int:
    job_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/view/4456242013/"
    DEBUG_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(job_url, wait_until="domcontentloaded", timeout=60_000)
            time.sleep(8)
            dump = page.evaluate(DUMP_JS)
            (DEBUG_DIR / "job-state.txt").write_text(dump, encoding="utf-8")
            print("[check] wrote job-state.txt", flush=True)
            page.screenshot(path=str(DEBUG_DIR / "job-state.png"))
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
