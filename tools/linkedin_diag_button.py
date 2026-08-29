"""Diagnose why the Easy Apply button is not found on job pages."""

from __future__ import annotations

import json
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"
JOB_URL = "https://www.linkedin.com/jobs/view/4458964711/"

JS = """() => {
  const out = {buttons: [], applyEls: [], applyClasses: [], topCard: ''};
  document.querySelectorAll('button').forEach(b => {
    const t = (b.innerText || '').trim().slice(0, 40);
    const al = b.getAttribute('aria-label') || '';
    if (t || al) out.buttons.push({t, al, cls: (b.className || '').toString().slice(0, 70)});
  });
  document.querySelectorAll('[aria-label*="Apply" i]').forEach(e => {
    out.applyEls.push({tag: e.tagName, al: e.getAttribute('aria-label'),
                       cls: (e.className || '').toString().slice(0, 70)});
  });
  document.querySelectorAll('[class*="apply" i]').forEach(e => {
    out.applyClasses.push({tag: e.tagName,
                           cls: (e.className || '').toString().slice(0, 90),
                           t: (e.innerText || '').trim().slice(0, 40)});
  });
  const tc = document.querySelector('.jobs-apply, .job-details-jobs-unified-top-card__header, .job-details-jobs-unified-top-card__primary-description-container');
  if (tc) out.topCard = (tc.innerText || '').slice(0, 300);
  return out;
}"""


def main() -> int:
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            no_viewport=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(JOB_URL, wait_until="domcontentloaded", timeout=45_000)
        time.sleep(6)
        info = page.evaluate(JS)
        print(json.dumps(info, indent=1)[:4000])
        context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
