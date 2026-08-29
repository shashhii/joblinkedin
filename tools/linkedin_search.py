"""Search LinkedIn for fresh Easy Apply jobs and save results to a file.

Designed for volume + freshness (used by the 100-application marathon):
  - Many keyword/location combos across India's tech hubs + remote.
  - Pagination (start=0/25/50) + aggressive scrolling to load all cards.
  - Experience levels: internship(1) + entry(2) + associate(3).
  - Easy Apply only (f_AL=true), posted in the past day or week, newest first.

Usage:
    python tools/linkedin_search.py [--fresh] [--headed]

    --fresh   Delete the previous results file before searching (hourly reset).

Writes tools/.search_results.txt with one job per line:
    <job_id> | <title> | <company> | <location> | <easy_apply> | <url>
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from patchright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
RESULTS_FILE = HERE / ".search_results.txt"
PROFILE_DIR = Path.home() / ".linkedin-mcp" / "profile"

# Chromium launch flags. The --no-sandbox / --disable-dev-shm-usage /
# --disable-gpu trio is required for headless Chromium on Render (Linux,
# 512MB, running as root); they are harmless no-ops on local Windows.
BROWSER_ARGS = [
    "--start-maximized",
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--no-first-run",
    "--no-default-browser-check",
]


def _inject_session(context) -> None:
    """Best-effort: inject LinkedIn cookies from tools/.session/cookies.json.

    On Render the persistent profile is empty, so the login comes from the
    R2-restored cookie file. Locally the profile already holds the session and
    this is a harmless refresh. Never raises.
    """
    try:
        import r2_sync
        cookies = r2_sync.load_cookies()
        if cookies:
            context.add_cookies(cookies)
            print(f"[search] injected {len(cookies)} session cookies", flush=True)
    except Exception as exc:
        print(f"[search] cookie inject skipped: {exc.__class__.__name__}", flush=True)

# (keywords, location) — entry/associate + Easy Apply filters applied in URL.
SEARCHES = [
    # Bengaluru
    ("software engineer", "Bengaluru"),
    ("full stack developer", "Bengaluru"),
    ("python developer", "Bengaluru"),
    ("android developer", "Bengaluru"),
    ("backend developer", "Bengaluru"),
    ("frontend developer", "Bengaluru"),
    ("java developer", "Bengaluru"),
    ("react developer", "Bengaluru"),
    ("machine learning", "Bengaluru"),
    ("data analyst", "Bengaluru"),
    ("data engineer", "Bengaluru"),
    ("devops engineer", "Bengaluru"),
    ("software developer", "Bengaluru"),
    # Mysore (preferred)
    ("software developer", "Mysore"),
    ("software engineer", "Mysore"),
    # Other hubs
    ("software engineer", "Hyderabad"),
    ("software developer", "Pune"),
    ("software engineer", "Chennai"),
    ("software developer", "Noida"),
    ("software engineer", "Gurugram"),
    ("full stack developer", "Hyderabad"),
    ("python developer", "Pune"),
    # Remote / India-wide
    ("AI engineer", "India"),
    ("frontend developer", "India"),
    ("react developer", "India"),
    ("backend developer", "India"),
    ("full stack developer", "India"),
    ("python developer", "India"),
    ("node.js developer", "India"),
    ("golang developer", "India"),
    ("dotnet developer", "India"),
    ("qa engineer", "India"),
    ("software engineer", "India"),
]

# Pagination offsets (LinkedIn returns ~25 results per page).
PAGE_STARTS = [0, 25, 50]


def extract_jobs(page) -> list[dict]:
    """Extract job cards from the current search results page."""
    jobs = []
    cards = page.locator("li.jobs-search-results__list-item, div.job-card-container").all()
    for card in cards:
        try:
            link = card.locator("a[href*='/jobs/view/']").first
            href = link.get_attribute("href") or ""
            m = re.search(r"/jobs/view/(\d+)", href)
            if not m:
                continue
            job_id = m.group(1)
            title = ""
            try:
                title = card.locator(
                    ".job-card-list__title--link strong, .job-card-container__link strong, .job-card-list__title--link"
                ).first.inner_text().strip()
            except Exception:
                try:
                    title = link.inner_text().strip()
                except Exception:
                    pass
            company = ""
            try:
                company = card.locator(
                    ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle"
                ).first.inner_text().strip()
            except Exception:
                pass
            location = ""
            try:
                location = card.locator(
                    ".job-card-container__metadata-item, .artdeco-entity-lockup__caption"
                ).first.inner_text().strip()
            except Exception:
                pass
            easy = False
            try:
                badge = card.locator(
                    ".job-card-container__apply-method, .jobs-universal-applied-link, "
                    "[class*='easy-apply'], .job-card-container__footer-wrapper"
                ).first.inner_text()
                easy = "easy apply" in badge.lower()
            except Exception:
                try:
                    btn = card.locator("button[aria-label*='Easy Apply'], a[aria-label*='Easy Apply']").first
                    easy = btn.count() > 0
                except Exception:
                    pass
            jobs.append({
                "id": job_id,
                "title": title.replace("\n", " "),
                "company": company.replace("\n", " "),
                "location": location.replace("\n", " "),
                "easy": easy,
                "url": f"https://www.linkedin.com/jobs/view/{job_id}/",
            })
        except Exception:
            continue
    return jobs


def scroll_to_load(page, rounds: int = 6) -> None:
    """Scroll the results pane so LinkedIn lazy-loads all cards on the page."""
    for _ in range(rounds):
        try:
            page.mouse.wheel(0, 3000)
        except Exception:
            break
        time.sleep(1.0)


def main() -> int:
    fresh = "--fresh" in sys.argv
    if fresh:
        try:
            if RESULTS_FILE.exists():
                RESULTS_FILE.unlink()
        except OSError:
            pass

    all_jobs: dict[str, dict] = {}
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless="--headed" not in sys.argv,
            no_viewport=True,
            args=BROWSER_ARGS,
        )
        _inject_session(context)
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for keywords, location in SEARCHES:
                for start in PAGE_STARTS:
                    url = (
                        "https://www.linkedin.com/jobs/search/?"
                        f"keywords={keywords.replace(' ', '+')}"
                        f"&location={location.replace(' ', '+')}"
                        "&f_E=1%2C2%2C3"   # internship + entry + associate
                        "&f_AL=true"       # Easy Apply only
                        "&f_TPR=r604800"   # past week
                        "&sortBy=DD"      # newest first
                        f"&start={start}"
                    )
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                        time.sleep(4)
                        scroll_to_load(page)
                        jobs = extract_jobs(page)
                        if not jobs:
                            break  # no more pages for this search
                        added = 0
                        for j in jobs:
                            if j["id"] not in all_jobs:
                                all_jobs[j["id"]] = j
                                added += 1
                        print(f"[search] '{keywords}' @ {location} start={start}: {len(jobs)} cards (+{added} new)", flush=True)
                        if len(jobs) < 10:
                            break  # last page
                    except Exception as exc:
                        print(f"[search] '{keywords}' @ {location} start={start} FAILED: {exc}", flush=True)
                    time.sleep(1.5)
        finally:
            context.close()

    lines = []
    for j in all_jobs.values():
        lines.append(
            f"{j['id']} | {j['title']} | {j['company']} | {j['location']} | "
            f"{'EASY' if j['easy'] else 'EXTERNAL'} | {j['url']}"
        )
    RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] {len(lines)} unique jobs -> {RESULTS_FILE}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
