"""Test: Easy Apply modal on a DIRECT job page (like linkedin_apply.py does)."""
import sys, time
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.__str__())
from patchright.sync_api import sync_playwright
from pathlib import Path

PROFILE = Path.home() / ".linkedin-mcp" / "profile"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE), headless=True, no_viewport=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # Navigate directly to a job page (like linkedin_apply.py does)
    job_url = "https://www.linkedin.com/jobs/view/4466998134/"
    print(f"[1] navigating to: {job_url}", flush=True)
    page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
    time.sleep(5)
    print(f"[2] URL: {page.url[:120]}", flush=True)
    print(f"[2b] TITLE: {page.title()[:80]}", flush=True)

    # Check for Easy Apply buttons
    easy = page.locator(
        "button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], "
        "a:has-text('Easy Apply'), a[aria-label*='Easy Apply'], .jobs-apply-button"
    )
    count = easy.count()
    print(f"[3] Easy Apply buttons: {count}", flush=True)

    for i in range(min(count, 5)):
        btn = easy.nth(i)
        tag = btn.evaluate("el => el.tagName")
        txt = btn.evaluate("el => (el.innerText || '').substring(0, 60)")
        aria = btn.evaluate("el => el.getAttribute('aria-label') || ''")
        visible = btn.is_visible()
        print(f"  btn[{i}]: tag={tag} text={txt!r} aria={aria!r} visible={visible}", flush=True)

    if count > 0:
        # Find the ACTUAL apply button (not the filter)
        apply_btn = None
        for i in range(count):
            btn = easy.nth(i)
            aria = btn.evaluate("el => el.getAttribute('aria-label') || ''")
            if "Easy Apply to" in aria:
                apply_btn = btn
                print(f"[4] using btn[{i}] (actual apply button)", flush=True)
                break

        if not apply_btn:
            # Fall back to first visible
            apply_btn = easy.first
            print("[4] using first button (no 'Easy Apply to' found)", flush=True)

        apply_btn.click(timeout=8000)
        print("[5] clicked!", flush=True)
        time.sleep(5)

        # Check for modal
        modal_sels = [
            "dialog",
            ".jobs-easy-apply-modal",
            "div[role='dialog']",
            ".artdeco-modal",
            ".artdeco-modal-overlay",
        ]
        for sel in modal_sels:
            c = page.locator(sel).count()
            if c > 0:
                txt = page.locator(sel).first.inner_text(timeout=3000)[:400]
                print(f"[6] MODAL FOUND ({sel}): {txt[:300]}", flush=True)
                break
        else:
            print("[6] NO MODAL found", flush=True)

            # Check new pages
            if len(ctx.pages) > 1:
                new_p = ctx.pages[-1]
                print(f"[6b] NEW PAGE: {new_p.url}", flush=True)

            # Broad search for any dialog-like element
            dialogs = page.evaluate("""() => {
                const all = document.querySelectorAll('*');
                const results = [];
                for (const el of all) {
                    const role = el.getAttribute('role') || '';
                    const cls = (typeof el.className === 'string') ? el.className : '';
                    const tag = el.tagName;
                    if (role === 'dialog' || tag === 'DIALOG' ||
                        cls.includes('easy-apply') || cls.includes('artdeco-modal') ||
                        cls.includes('application-form')) {
                        results.push({
                            tag, role,
                            cls: cls.substring(0, 120),
                            text: (el.innerText || '').substring(0, 150)
                        });
                    }
                }
                return results;
            }""")
            print(f"[6c] dialogs: {dialogs}", flush=True)

            # Check current URL
            print(f"[6d] URL now: {page.url[:120]}", flush=True)

    ctx.close()
    print("[done]", flush=True)
