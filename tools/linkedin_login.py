"""One-shot interactive LinkedIn login for the career-ops job pipeline.

Flow
----
1. Opens a VISIBLE Chromium (Patchright) window reusing the
   mcp-server-linkedin profile dir (~/.linkedin-mcp/profile) so the session
   is picked up by the LinkedIn MCP server afterwards.
2. Fills email + password automatically (from tools/.linkedin.env or env vars).
3. Handles CAPTCHA / checkpoint pages by pausing and letting the user solve
   them in the visible window.
4. When LinkedIn asks for the 2FA code, writes NEED_OTP to the status file
   and waits for the code to appear in the OTP file (the assistant asks the
   user in chat and writes it there).
5. On success writes DONE; the session persists in the profile directory.

Handshake files (inside tools/):
    .linkedin_login_status.txt   script -> assistant
    .linkedin_otp.txt            assistant -> script (one-time code)
    .linkedin.env                credentials (email / password)
    .linkedin_debug/             screenshots for diagnostics
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
STATUS_FILE = HERE / ".linkedin_login_status.txt"
OTP_FILE = HERE / ".linkedin_otp.txt"
DEBUG_DIR = HERE / ".linkedin_debug"
PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"

LOGGED_IN_MARKERS = ("/feed", "/mynetwork", "/jobs", "/in/", "/me", "/notifications")

OTP_SELECTORS = [
    "#input__email_verification_pin",
    "input[name='pin']",
    "#multifactor-code",
    "#verification-code",
    "input[inputmode='numeric']",
    "input[autocomplete='one-time-code']",
]


def status(msg: str) -> None:
    STATUS_FILE.write_text(msg, encoding="utf-8")
    print(f"[status] {msg}", flush=True)


def snap(page, name: str) -> None:
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=False)
        (DEBUG_DIR / f"{name}.url.txt").write_text(page.url, encoding="utf-8")
    except Exception:
        pass


def read_credentials() -> tuple[str, str]:
    values: dict[str, str] = {}
    env_file = HERE / ".linkedin.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    email = os.environ.get("LINKEDIN_EMAIL") or values.get("LINKEDIN_EMAIL", "")
    password = os.environ.get("LINKEDIN_PASSWORD") or values.get(
        "LINKEDIN_PASSWORD", ""
    )
    return email, password


def is_logged_in(page) -> bool:
    url = page.url
    return any(marker in url for marker in LOGGED_IN_MARKERS)


def is_challenge(page) -> bool:
    url = page.url.lower()
    return any(k in url for k in ("checkpoint", "challenge", "captcha", "uas/login"))


def find_otp_input(page):
    for selector in OTP_SELECTORS:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=400):
                return locator
        except Exception:
            continue
    return None


def wait_for_otp(timeout_seconds: int = 600) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            if OTP_FILE.exists():
                code = OTP_FILE.read_text(encoding="utf-8").strip()
                if code:
                    return code
        except OSError:
            pass
        time.sleep(1)
    return ""


def try_fill(page, selector: str, value: str, timeout_ms: int = 8000) -> bool:
    try:
        loc = page.locator(selector).first
        loc.wait_for(state="visible", timeout=timeout_ms)
        loc.fill(value)
        return True
    except Exception:
        return False


def try_click_submit(page, timeout_ms: int = 5000) -> bool:
    selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Sign in')",
        "button:has-text('Next')",
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=timeout_ms):
                btn.click()
                return True
        except Exception:
            continue
    return False


def main() -> int:
    email, password = read_credentials()
    if not email or not password:
        status("FAILED:missing-credentials")
        return 2
    if OTP_FILE.exists():
        try:
            OTP_FILE.unlink()
        except OSError:
            pass
    status("STARTING")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        exit_code = 1
        try:
            page.goto(
                "https://www.linkedin.com/login",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            time.sleep(4)
            snap(page, "01-landing")

            if is_logged_in(page):
                status("DONE:already-logged-in")
                return 0

            # --- Step 1: email ---
            status("FILLING_EMAIL")
            filled_email = try_fill(page, "#username", email)
            if not filled_email:
                # Some layouts use a different id
                filled_email = try_fill(page, "input[name='session_key']", email)
            snap(page, "02-email-filled")
            if filled_email:
                try_click_submit(page)
                time.sleep(3)
                snap(page, "03-after-email-submit")

            # --- Step 2: password (may be same page or next page) ---
            status("FILLING_PASSWORD")
            filled_pw = try_fill(page, "#password", password, timeout_ms=15000)
            if not filled_pw:
                filled_pw = try_fill(
                    page, "input[name='session_password']", password, timeout_ms=5000
                )
            if not filled_pw:
                # Maybe a challenge/captcha appeared instead
                snap(page, "04-no-password-field")
                if is_challenge(page):
                    status("NEED_MANUAL_HELP:captcha-or-checkpoint-before-password")
                    # Wait for user to solve in visible window
                    deadline = time.time() + 300
                    while time.time() < deadline:
                        if is_logged_in(page) or find_otp_input(page):
                            break
                        time.sleep(3)
                    filled_pw = try_fill(page, "#password", password, timeout_ms=5000)
                if not filled_pw:
                    status(f"FAILED:password-field-not-found:{page.url}")
                    return 5

            snap(page, "05-password-filled")
            try_click_submit(page)
            time.sleep(4)
            snap(page, "06-after-password-submit")

            # --- Step 3: post-password — OTP, challenge, or logged in ---
            deadline = time.time() + 180
            while time.time() < deadline:
                if is_logged_in(page):
                    status("DONE")
                    time.sleep(5)
                    exit_code = 0
                    break

                otp_locator = find_otp_input(page)
                if otp_locator is not None:
                    status("NEED_OTP")
                    snap(page, "07-otp-screen")
                    code = wait_for_otp()
                    if not code:
                        status("FAILED:otp-timeout")
                        return 3
                    otp_locator.fill(code)
                    try:
                        page.locator("button[type='submit']").first.click(timeout=5000)
                    except Exception:
                        try:
                            otp_locator.press("Enter")
                        except Exception:
                            pass
                    status("SUBMITTED_OTP")
                    time.sleep(5)
                    snap(page, "08-after-otp")
                    deadline = time.time() + 120
                    continue

                if is_challenge(page):
                    status("NEED_MANUAL_HELP:checkpoint-or-captcha-after-password")
                    snap(page, "09-challenge")
                    deadline = max(deadline, time.time() + 180)
                    time.sleep(8)
                    continue

                time.sleep(2)

            if exit_code != 0:
                if is_logged_in(page):
                    status("DONE")
                    exit_code = 0
                else:
                    snap(page, "10-final")
                    status(f"FAILED:login-did-not-complete:{page.url}")
        finally:
            context.close()
        return exit_code


if __name__ == "__main__":
    sys.exit(main())
