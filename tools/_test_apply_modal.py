"""Quick test: can we click Easy Apply and see the modal render?"""
import sys, time, traceback
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.__str__())
from patchright.sync_api import sync_playwright
from pathlib import Path

PROFILE = Path.home() / ".linkedin-mcp" / "profile"

# Use a fresh search to find a real Easy Apply job
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE), headless=True, no_viewport=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # First, search for a job
    search_url = ("https://www.linkedin.com/jobs/search/"
                  "?keywords=python+developer&location=India"
                  "&f_E=1%2C2%2C3&f_AL=true&f_TPR=r604800&sortBy=DD&start=0")
    print(f"[1] searching: {search_url[:80]}", flush=True)
    page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
    time.sleep(4)

    # Find first job card link
    links = page.locator("a[href*='/jobs/view/']").all()
    print(f"[2] found {len(links)} job links", flush=True)

    if not links:
        print("NO JOB LINKS FOUND", flush=True)
        ctx.close()
        sys.exit(1)

    # Click first job to load its detail pane
    href = links[0].get_attribute("href", timeout=2000) or ""
    print(f"[3] clicking first job: {href[:80]}", flush=True)
    links[0].click(timeout=5000)
    time.sleep(3)

    # Now look for Easy Apply button
    easy_sels = (
        "button:has-text('Easy Apply'), "
        "button[aria-label*='Easy Apply'], "
        "a:has-text('Easy Apply'), "
        "a[aria-label*='Easy Apply'], "
        ".jobs-apply-button"
    )
    easy = page.locator(easy_sels)
    count = easy.count()
    print(f"[4] Easy Apply buttons: {count}", flush=True)

    if count == 0:
        # Try navigating directly to the job page
        import re
        m = re.search(r"/jobs/view/(\d+)", href)
        if m:
            direct_url = f"https://www.linkedin.com/jobs/view/{m.group(1)}/"
            print(f"[4b] trying direct URL: {direct_url}", flush=True)
            page.goto(direct_url, wait_until="domcontentloaded", timeout=30_000)
            time.sleep(4)
            count = easy.count()
            print(f"[4c] Easy Apply buttons after direct nav: {count}", flush=True)

    if count > 0:
        print("[5] clicking Easy Apply...", flush=True)
        try:
            easy.first.click(timeout=8000)
            print("[5] clicked!", flush=True)
        except Exception as e:
            print(f"[5] click failed: {e}", flush=True)
            ctx.close()
            sys.exit(1)

        time.sleep(3)

        # Check for modal with multiple selectors
        modal_sels = [
            "dialog",
            ".jobs-easy-apply-modal",
            "div[role='dialog']",
            ".artdeco-modal",
            ".artdeco-modal-overlay",
            "[data-test-modal]",
        ]
        for sel in modal_sels:
            c = page.locator(sel).count()
            if c > 0:
                txt = page.locator(sel).first.inner_text(timeout=3000)[:300]
                print(f"[6] MODAL ({sel}): {txt[:200]}", flush=True)
                break
        else:
            print("[6] NO MODAL found with any selector", flush=True)
            # Dump what's on the page
            body = page.evaluate(
                "() => document.body.innerText.substring(0, 1000)"
            )
            print(f"[6b] BODY: {body[:500]}", flush=True)

            # Check for any overlay/dialog elements
            overlays = page.evaluate("""() => {
                const els = document.querySelectorAll('dialog, [role="dialog"], .artdeco-modal, [class*="modal"], [class*="overlay"]');
                return Array.from(els).map(e => ({
                    tag: e.tagName,
                    cls: e.className.substring(0, 100),
                    visible: e.offsetParent !== null || e.style.display !== 'none',
                    text: (e.innerText || '').substring(0, 100)
                }));
            }""")
            print(f"[6c] OVERLAYS: {overlays}", flush=True)
    else:
        print("[5] No Easy Apply button found at all", flush=True)
        body = page.evaluate(
            "() => document.body.innerText.substring(0, 800)"
        )
        print(f"BODY: {body[:400]}", flush=True)

    ctx.close()
    print("[done]", flush=True)
