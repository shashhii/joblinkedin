"""Deep-diagnose the Easy Apply modal, including iframes.

Writes tools/.apply_debug/:
  - page-structure.txt   : frames, dialogs, top-level containers, body text head
  - modal-dump.txt       : the Easy Apply form fields (searching all frames)
  - modal-dump-after-next.txt : same after one Next click
  - diag-*.png           : screenshots
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DEBUG_DIR = HERE / ".apply_debug"
PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"

STRUCTURE_JS = """
() => {
  let out = 'URL: ' + location.href + '\\n\\n';
  out += '=== IFRAMES (' + document.querySelectorAll('iframe').length + ') ===\\n';
  document.querySelectorAll('iframe').forEach((f, i) => {
    out += i + ' src=' + (f.src || '(none)') + ' id=' + (f.id || '') + '\\n';
  });
  out += '\\n=== DIALOG/MODAL CANDIDATES ===\\n';
  const sels = ['.jobs-easy-apply-modal', 'div[role="dialog"]', '.artdeco-modal',
                '.jobs-apply-modal', '[data-test-modal]', '.modal', 'dialog'];
  sels.forEach((s) => {
    const n = document.querySelectorAll(s).length;
    if (n) out += s + ' -> ' + n + '\\n';
  });
  out += '\\n=== BODY TEXT (first 1500 chars) ===\\n';
  out += (document.body.innerText || '').slice(0, 1500);
  return out;
}
"""

FIELDS_JS = """
() => {
  const modal = document.querySelector('.jobs-easy-apply-modal') ||
                document.querySelector('div[role="dialog"]') ||
                document.querySelector('.artdeco-modal') ||
                document.querySelector('.jobs-apply-modal') ||
                document.body;
  let out = '=== MODAL TEXT (first 2000) ===\\n' + (modal.innerText || '').slice(0, 2000) + '\\n\\n=== FIELDS ===\\n';
  modal.querySelectorAll('input, select, textarea, button').forEach((el) => {
    const label = el.closest('.jobs-easy-apply-form-element, .artdeco-text-input, fieldset, label, div');
    out += [
      el.tagName, 'type=' + (el.type || ''), 'name=' + (el.name || ''),
      'id=' + (el.id || ''), 'value=' + (el.value || ''), 'checked=' + el.checked,
      'required=' + el.required, 'visible=' + (el.offsetParent !== null),
      'text=' + (el.innerText || '').slice(0, 60).replace(/\\n/g, ' '),
      'label=' + (label ? (label.innerText || '').slice(0, 100).replace(/\\n/g, ' | ') : ''),
    ].join(' ; ') + '\\n';
  });
  return out;
}
"""


def dump_all_frames(page, tag: str) -> None:
    """Run FIELDS_JS in the main frame and every child frame; save combined."""
    parts = [f"##### FRAME DUMP: {tag} #####\n"]
    frames = [page.main_frame] + page.frames[1:]
    for idx, frame in enumerate(frames):
        try:
            url = frame.url
            parts.append(f"\n----- frame[{idx}] url={url} -----\n")
            parts.append(frame.evaluate(FIELDS_JS))
        except Exception as exc:
            parts.append(f"(frame[{idx}] error: {exc.__class__.__name__})\n")
    (DEBUG_DIR / f"modal-dump-{tag}.txt").write_text("".join(parts), encoding="utf-8")
    print(f"[diag] wrote modal-dump-{tag}.txt", flush=True)


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

            structure = page.evaluate(STRUCTURE_JS)
            (DEBUG_DIR / "page-structure.txt").write_text(structure, encoding="utf-8")
            print("[diag] wrote page-structure.txt", flush=True)
            page.screenshot(path=str(DEBUG_DIR / "diag-01-before-easyapply.png"))

            easy = page.locator(
                "button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], .jobs-apply-button"
            ).first
            easy.wait_for(state="visible", timeout=15_000)
            easy.click()
            print("[diag] clicked Easy Apply", flush=True)
            time.sleep(6)  # give the modal more time to render
            page.screenshot(path=str(DEBUG_DIR / "diag-02-modal.png"))

            structure2 = page.evaluate(STRUCTURE_JS)
            (DEBUG_DIR / "page-structure-after.txt").write_text(structure2, encoding="utf-8")

            dump_all_frames(page, "initial")

            # Click Next once.
            clicked = False
            for text in ["Next", "Continue", "Review"]:
                try:
                    btn = page.get_by_role("button", name=text).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        print(f"[diag] clicked '{text}'", flush=True)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                print("[diag] no Next/Continue/Review button found", flush=True)
            time.sleep(4)
            page.screenshot(path=str(DEBUG_DIR / "diag-03-after-next.png"))
            dump_all_frames(page, "after-next")
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
