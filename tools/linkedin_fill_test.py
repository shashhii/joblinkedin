"""Focused test: open Easy Apply, fill the phone input, read back the value.

Writes tools/.apply_debug/fill-test.txt with a step-by-step log so we can see
exactly whether the phone field accepts the value and why Next may fail.
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

log_lines = []


def log(msg: str) -> None:
    log_lines.append(msg)
    print(f"[test] {msg}", flush=True)


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
            log(f"loaded: {page.url}")

            easy = page.locator(
                "button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], .jobs-apply-button"
            ).first
            easy.wait_for(state="visible", timeout=15_000)
            easy.click()
            time.sleep(5)
            log("clicked Easy Apply")

            # Enumerate every tel input in the main frame with visibility + value.
            tel_count = page.locator("input[type='tel']").count()
            log(f"tel inputs in main frame: {tel_count}")
            for i in range(tel_count):
                loc = page.locator("input[type='tel']").nth(i)
                try:
                    vis = loc.is_visible(timeout=300)
                    val = loc.input_value() if vis else "(hidden)"
                    log(f"  tel[{i}] visible={vis} value='{val}'")
                except Exception as exc:
                    log(f"  tel[{i}] error={exc.__class__.__name__}")

            # Try to fill each visible tel input and read back.
            for i in range(tel_count):
                loc = page.locator("input[type='tel']").nth(i)
                try:
                    if not loc.is_visible(timeout=300):
                        continue
                    loc.click(timeout=2000)
                    loc.fill(PHONE)
                    time.sleep(0.5)
                    readback = loc.input_value()
                    log(f"  fill tel[{i}] -> readback='{readback}' match={readback == PHONE}")
                    if readback != PHONE:
                        # Fallback: type sequentially.
                        loc.fill("")
                        loc.press_sequentially(PHONE, delay=50)
                        time.sleep(0.5)
                        readback2 = loc.input_value()
                        log(f"  press_sequentially tel[{i}] -> readback='{readback2}'")
                except Exception as exc:
                    log(f"  fill tel[{i}] error={exc.__class__.__name__}: {exc}")

            time.sleep(1)
            page.screenshot(path=str(DEBUG_DIR / "fill-test-after.png"))

            # Now click Next and report the resulting page text / errors.
            next_btn = page.get_by_role("button", name="Next").first
            try:
                if next_btn.is_visible(timeout=2000):
                    next_btn.click()
                    log("clicked Next")
                    time.sleep(3)
            except Exception as exc:
                log(f"Next click error={exc.__class__.__name__}")

            page.screenshot(path=str(DEBUG_DIR / "fill-test-after-next.png"))

            # Capture any validation error text and the current page indicator.
            try:
                indicator = page.evaluate(
                    "() => { const el = document.querySelector('.jobs-easy-apply-modal, div[role=\"dialog\"]'); "
                    "return el ? (el.innerText || '').slice(0, 400) : 'no modal'; }"
                )
                log("modal text after Next:\n" + indicator)
            except Exception as exc:
                log(f"modal text error={exc.__class__.__name__}")

        finally:
            (DEBUG_DIR / "fill-test.txt").write_text("\n".join(log_lines), encoding="utf-8")
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
