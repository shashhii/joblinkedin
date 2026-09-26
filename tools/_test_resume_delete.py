"""Test clicking show options and deleting a resume on the settings page."""
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
    page.goto(SETTINGS_URL, wait_until="domcontentloaded", timeout=30_000)
    time.sleep(3)

    # Find all options buttons
    option_btns = page.locator("button:has-text('Show options for')").all()
    print(f"Found {len(option_btns)} 'Show options' buttons", flush=True)

    for i, btn in enumerate(option_btns):
        btn_text = btn.inner_text()
        print(f"  [{i}] Button text: {btn_text!r}", flush=True)

    if option_btns:
        # Click the options button for the first or last resume
        print("Clicking first options button...", flush=True)
        option_btns[0].click()
        time.sleep(1)

        # Look for menu items that appeared
        menu_items = page.evaluate("""() => {
            const dropdowns = document.querySelectorAll('.artdeco-dropdown__item, [role="menuitem"], div[role="button"], button');
            return Array.from(dropdowns).filter(d => {
                const t = (d.innerText || '').toLowerCase();
                return t.includes('delete') || t.includes('download');
            }).map(d => ({
                tag: d.tagName,
                text: (d.innerText || '').trim(),
                aria: d.getAttribute('aria-label') || ''
            }));
        }""")
        print(f"Menu items after clicking options: {menu_items}", flush=True)

    ctx.close()
    print("[done]", flush=True)
