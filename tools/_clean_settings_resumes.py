"""Delete temporary/tailored resumes from LinkedIn's application settings page."""
import sys, time, json
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.__str__())
from patchright.sync_api import sync_playwright
from pathlib import Path

PROFILE = Path.home() / ".linkedin-mcp" / "profile"
COOKIE_FILE = Path(__file__).resolve().parent / ".session" / "cookies.json"
SETTINGS_URL = "https://www.linkedin.com/jobs/application-settings/?hideTitle=true"

# Primary resumes that should NEVER be deleted
KEEP_RESUMES = ["shashhii.pdf", "shashikumar", "resume.pdf"]


def clean_application_settings_resumes(page, keep_names: list[str] | None = None) -> int:
    """Delete all temporary tailored resumes from LinkedIn application settings page."""
    keep = [k.lower() for k in (keep_names or KEEP_RESUMES)]
    deleted_count = 0
    try:
        page.goto(SETTINGS_URL, wait_until="domcontentloaded", timeout=30_000)
        time.sleep(3)

        # Loop until all temporary resumes are removed
        for _ in range(10):
            # Find all "Show options for ..." buttons
            btns = page.locator("button[aria-label*='options'], button:has-text('Show options for')").all()
            target_btn = None
            target_name = ""

            for b in btns:
                txt = (b.inner_text() or b.get_attribute("aria-label") or "").strip()
                # Extract filename from "Show options for <filename>"
                name = txt.replace("Show options for", "").strip()
                name_lower = name.lower()

                # If this resume is NOT in the keep list, delete it
                is_keep = any(k in name_lower for k in keep)
                if not is_keep and name:
                    target_btn = b
                    target_name = name
                    break

            if not target_btn:
                break

            print(f"Deleting temporary resume: {target_name!r}", flush=True)
            target_btn.click()
            time.sleep(0.8)

            # Click "Delete" from the menu
            del_option = page.locator("div:has-text('Delete'), button:has-text('Delete'), [role='menuitem']:has-text('Delete')").first
            if del_option.count() > 0 and del_option.is_visible():
                del_option.click()
                time.sleep(0.8)

                # Check if confirmation dialog appears
                confirm_btn = page.locator("button.artdeco-button--primary:has-text('Delete'), [data-test-modal] button:has-text('Delete')").first
                if confirm_btn.count() > 0 and confirm_btn.is_visible():
                    confirm_btn.click()
                    time.sleep(1)

                deleted_count += 1
                print(f"Deleted: {target_name}", flush=True)
                time.sleep(1)
            else:
                break
    except Exception as exc:
        print(f"Error cleaning resumes: {exc}", flush=True)
    return deleted_count


if __name__ == "__main__":
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
        n = clean_application_settings_resumes(page)
        print(f"Total deleted: {n}", flush=True)
        ctx.close()
