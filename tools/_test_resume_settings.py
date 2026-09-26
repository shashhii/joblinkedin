"""Inspect and clean up stored resumes on LinkedIn's application settings page."""
import sys, time, json
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.__str__())
from patchright.sync_api import sync_playwright
from pathlib import Path

PROFILE = Path.home() / ".linkedin-mcp" / "profile"
COOKIE_FILE = Path(__file__).resolve().parent / ".session" / "cookies.json"
SETTINGS_URL = "https://www.linkedin.com/jobs/application-settings/?hideTitle=true"

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE), headless=True, no_viewport=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    if COOKIE_FILE.exists():
        try:
            cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            ctx.add_cookies(cookies)
        except Exception:
            pass

    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    print(f"[1] Navigating to: {SETTINGS_URL}", flush=True)
    page.goto(SETTINGS_URL, wait_until="domcontentloaded", timeout=30_000)
    time.sleep(5)

    print(f"[2] URL: {page.url}", flush=True)
    print(f"[2b] TITLE: {page.title()}", flush=True)

    # Inspect all elements on this page
    body_text = page.evaluate("() => document.body.innerText.substring(0, 1500)")
    print(f"[3] Body Text:\n{body_text[:500]}", flush=True)

    # Look for all buttons, menus, cards on application-settings page
    elements = page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('button, a, [role="button"], div[data-test-document-card], li, .ui-attachment').forEach((el) => {
            const t = (el.innerText || el.getAttribute('aria-label') || '').trim();
            if (t.toLowerCase().includes('delete') || t.toLowerCase().includes('option') ||
                t.toLowerCase().includes('more') || t.toLowerCase().includes('resume') ||
                t.toLowerCase().includes('cv') || t.includes('.pdf')) {
                results.push({
                    tag: el.tagName,
                    aria: el.getAttribute('aria-label') || '',
                    text: t.substring(0, 80),
                    cls: (el.className || '').substring(0, 80)
                });
            }
        });
        return results;
    }""")
    print(f"[4] Resume/action elements ({len(elements)}):", flush=True)
    for e in elements[:20]:
        print(f"  {e['tag']} | text={e['text']!r} | aria={e['aria']!r}", flush=True)

    ctx.close()
    print("[done]", flush=True)
