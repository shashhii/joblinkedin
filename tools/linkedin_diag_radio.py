"""Advance to the screening-questions screen and dump the raw HTML of the
question area so we can see exactly how radios are structured."""

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
  let out = '=== MODAL innerText (first 800) ===\\n' + (m.innerText || '').slice(0, 800) + '\\n\\n';
  out += '=== RAW HTML of form area (first 6000 chars) ===\\n';
  const form = m.querySelector('form') || m;
  out += form.innerHTML.slice(0, 6000);
  return out;
}
"""


def main() -> int:
    job_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.linkedin.com/jobs/view/4455886125/"
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
            time.sleep(6)

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
            page.get_by_role("button", name="Next").first.click()
            time.sleep(3)

            # Screen 2 (Resume): upload + Next.
            try:
                btn = page.get_by_role("button", name="Upload resume").first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    time.sleep(1.5)
            except Exception:
                pass
            try:
                fi = page.locator("input[type='file']").first
                fi.set_input_files(str(HERE.parent / "career-ops" / "output" / "cv-infosys-fullstack.pdf"))
                time.sleep(2)
            except Exception:
                pass
            page.get_by_role("button", name="Next").first.click()
            time.sleep(3)

            # Screen 3 (Top choice): Next.
            page.get_by_role("button", name="Next").first.click()
            time.sleep(3)

            # Now on screening questions screen — dump.
            dump = page.evaluate(DUMP_JS)
            (DEBUG_DIR / "radio-dump.txt").write_text(dump, encoding="utf-8")
            print("[diag] wrote radio-dump.txt", flush=True)
            page.screenshot(path=str(DEBUG_DIR / "radio-screen.png"))
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
