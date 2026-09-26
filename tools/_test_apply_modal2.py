"""Test: does Easy Apply open a new page/tab instead of a modal?"""
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

    # Search
    search_url = ("https://www.linkedin.com/jobs/search/"
                  "?keywords=python+developer&location=India"
                  "&f_E=1%2C2%2C3&f_AL=true&f_TPR=r604800&sortBy=DD&start=0")
    page.goto(search_url, wait_until="domcontentloaded", timeout=30_000)
    time.sleep(4)

    # Click first job
    links = page.locator("a[href*='/jobs/view/']").all()
    print(f"[1] {len(links)} job links", flush=True)
    if links:
        links[0].click(timeout=5000)
        time.sleep(3)

    # Count pages before click
    pages_before = len(ctx.pages)
    print(f"[2] pages before Easy Apply click: {pages_before}", flush=True)

    # Click Easy Apply
    easy = page.locator(
        "button:has-text('Easy Apply'), button[aria-label*='Easy Apply'], "
        "a:has-text('Easy Apply'), a[aria-label*='Easy Apply'], .jobs-apply-button"
    )
    count = easy.count()
    print(f"[3] Easy Apply buttons: {count}", flush=True)

    if count > 0:
        # Log each button's tag, text, aria-label
        for i in range(min(count, 5)):
            btn = easy.nth(i)
            tag = btn.evaluate("el => el.tagName")
            txt = btn.evaluate("el => (el.innerText || '').substring(0, 60)")
            aria = btn.evaluate("el => el.getAttribute('aria-label') || ''")
            href_attr = btn.evaluate("el => el.getAttribute('href') || ''")
            print(f"  btn[{i}]: tag={tag} text={txt!r} aria={aria!r} href={href_attr!r}", flush=True)

        # Click the first one
        easy.first.click(timeout=8000)
        print("[4] clicked Easy Apply", flush=True)
        time.sleep(5)

        # Check for new pages
        pages_after = len(ctx.pages)
        print(f"[5] pages after click: {pages_after}", flush=True)

        if pages_after > pages_before:
            new_page = ctx.pages[-1]
            print(f"[5b] NEW PAGE URL: {new_page.url}", flush=True)
            time.sleep(3)
            body = new_page.evaluate("() => document.body.innerText.substring(0, 600)")
            print(f"[5c] NEW PAGE BODY: {body[:400]}", flush=True)
        else:
            # Check current page URL (maybe navigated)
            print(f"[5b] current URL: {page.url[:120]}", flush=True)

            # Wait a bit more and check for modal with broader selectors
            time.sleep(3)
            all_dialogs = page.evaluate("""() => {
                const all = document.querySelectorAll('*');
                const results = [];
                for (const el of all) {
                    const role = el.getAttribute('role') || '';
                    const cls = el.className || '';
                    const tag = el.tagName;
                    if (role === 'dialog' || tag === 'DIALOG' ||
                        (typeof cls === 'string' && (cls.includes('easy-apply') || cls.includes('artdeco-modal')))) {
                        results.push({
                            tag: tag,
                            role: role,
                            cls: (typeof cls === 'string' ? cls : '').substring(0, 120),
                            text: (el.innerText || '').substring(0, 150)
                        });
                    }
                }
                return results;
            }""")
            print(f"[6] dialog/modal elements: {all_dialogs}", flush=True)

            # Also check if the page URL changed (redirect to apply page)
            if "easy-apply" in page.url or "apply" in page.url:
                print("[7] Page navigated to apply URL!", flush=True)
                body = page.evaluate("() => document.body.innerText.substring(0, 600)")
                print(f"[7b] BODY: {body[:400]}", flush=True)

    ctx.close()
    print("[done]", flush=True)
