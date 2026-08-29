"""Advance the Easy Apply flow to the screening-questions screen and dump its
exact DOM structure (inputs, buttons, labels) to tools/.apply_debug/screen4.txt.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DEBUG_DIR = HERE / ".apply_debug"
PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"
PHONE = "8431250682"

DUMP_JS = """
() => {
  const m = document.querySelector('dialog, .jobs-easy-apply-modal, div[role="dialog"]') || document.body;
  let out = '=== TEXT (first 1200) ===\\n' + (m.innerText || '').slice(0, 1200) + '\\n\\n=== ALL ELEMENTS ===\\n';
  m.querySelectorAll('input, select, textarea, button, [role="radio"], [role="radiogroup"], label').forEach((el) => {
    out += [
      el.tagName,
      'type=' + (el.type || ''),
      'role=' + (el.getAttribute('role') || ''),
      'name=' + (el.name || ''),
      'id=' + (el.id || ''),
      'value=' + (el.value || ''),
      'checked=' + el.checked,
      'aria-checked=' + (el.getAttribute('aria-checked') || ''),
      'visible=' + (el.offsetParent !== null),
      'text=' + (el.innerText || '').slice(0, 50).replace(/\\n/g, ' '),
      'class=' + (el.className || '').toString().slice(0, 80),
    ].join(' ; ') + '\\n';
  });
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
            time.sleep(5)

            easy = page.locator(
                "button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], .jobs-apply-button"
            ).first
            easy.wait_for(state="visible", timeout=15_000)
            easy.click()
            time.sleep(5)

            # Screen 1: fill phone, Next.
            tel = page.locator("input[type='tel']").first
            if tel.is_visible(timeout=3000):
                tel.click()
                tel.fill(PHONE)
                print("[diag] filled phone", flush=True)
            page.get_by_role("button", name="Next").first.click()
            time.sleep(3)
            print("[diag] -> screen 2", flush=True)

            # Screen 2 (Resume): Next (keep whatever resume is selected).
            page.get_by_role("button", name="Next").first.click()
            time.sleep(3)
            print("[diag] -> screen 3", flush=True)

            # Screen 3 (Top choice optional): Next.
            page.get_by_role("button", name="Next").first.click()
            time.sleep(3)
            print("[diag] -> screen 4", flush=True)

            dump = page.evaluate(DUMP_JS)
            (DEBUG_DIR / "screen4.txt").write_text(dump, encoding="utf-8")
            print("[diag] wrote screen4.txt", flush=True)
            page.screenshot(path=str(DEBUG_DIR / "screen4.png"))
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
