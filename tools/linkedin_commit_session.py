"""Commit a logged-in LinkedIn profile so mcp-server-linkedin accepts it.

The MCP daemon's auth gate (_auth_ready) requires three artifacts:
  1. ~/.linkedin-mcp/profile/          (non-empty browser profile)
  2. ~/.linkedin-mcp/cookies.json      (portable cookie export)
  3. ~/.linkedin-mcp/source-state.json (session metadata)

This script opens the existing profile with Patchright, verifies the li_at
session cookie is present, exports cookies in the exact Playwright format the
daemon expects, and writes source-state.json with the exact schema from
linkedin_mcp_server.session_state.write_source_state.

Run this AFTER linkedin_login.py reports DONE, with no mcp-server-linkedin
daemon or Chrome-for-Testing processes running (they would hold the profile).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from patchright.sync_api import sync_playwright

AUTH_ROOT = Path.home() / ".linkedin-mcp"
PROFILE_DIR = AUTH_ROOT / "profile"
COOKIES_PATH = AUTH_ROOT / "cookies.json"
SOURCE_STATE_PATH = AUTH_ROOT / "source-state.json"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    if not PROFILE_DIR.is_dir() or not any(PROFILE_DIR.iterdir()):
        print("[commit] FAILED: profile dir missing or empty", flush=True)
        return 2

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            time.sleep(4)
            final_url = page.url
            cookies = context.cookies()
        finally:
            context.close()

    li_at = [c for c in cookies if c.get("name") == "li_at"]
    if not li_at:
        print(
            f"[commit] FAILED: no li_at session cookie (final url: {final_url})",
            flush=True,
        )
        return 3

    # 1. Portable cookie export (Playwright storage-state cookie list).
    COOKIES_PATH.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    print(f"[commit] wrote {COOKIES_PATH} ({len(cookies)} cookies)", flush=True)

    # 2. Source session metadata (exact schema of write_source_state).
    state = {
        "version": 1,
        "source_runtime_id": "windows-amd64-host",
        "login_generation": str(uuid.uuid4()),
        "created_at": utcnow_iso(),
        "profile_path": str(PROFILE_DIR),
        "cookies_path": str(COOKIES_PATH),
    }
    SOURCE_STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(f"[commit] wrote {SOURCE_STATE_PATH}", flush=True)
    print("[commit] DONE: session committed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
