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

import os
import random
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
    # --- Memory savers (Render free tier = 512MB, shared with Flask + marathon) ---
    # Cap the V8 heap per renderer; this is the single biggest lever.
    "--js-flags=--max-old-space-size=128",
    # Disable heavy/unnecessary features that allocate memory.
    "--disable-features=Translate,OptimizationHints,InterestFeedContentSuggestions,"
    "PrivacySandboxSettings4,ThirdPartyStoragePartitioning,VizDisplayCompositor,"
    "PaintHolding,MediaRouter,AudioService",
    "--disable-background-networking",
    "--disable-component-update",
    "--mute-audio",
    "--disable-logging",
    "--disable-breakpad",
    "--disable-crash-reporter",
    "--disable-hang-monitor",
    "--disable-notifications",
    "--disable-sync",
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


def _job_id_from_href(href: str) -> str | None:
    """Extract the numeric job ID from a LinkedIn job URL.

    Current DOM uses slug URLs:  /jobs/view/<slug>-<id>?...
    Older DOM used numeric URLs: /jobs/view/<id>/
    """
    m = re.search(r"/jobs/view/(\d+)", href)
    if m:
        return m.group(1)
    path = href.split("?", 1)[0]
    m2 = re.search(r"(\d+)$", path)
    return m2.group(1) if m2 else None


def extract_jobs(page) -> list[dict]:
    """Extract job cards from the current search results page.

    LinkedIn's DOM changes over time. The current (2026) card container is
    ``div.job-search-card`` and the job link is a slug URL. The older
    selectors are kept as fallbacks so a future DOM change degrades
    gracefully instead of silently returning 0 jobs.
    """
    jobs = []
    cards = page.locator(
        "div.job-search-card, div.job-card-container, li.jobs-search-results__list-item"
    ).all()
    for card in cards:
        try:
            link = card.locator("a[href*='/jobs/view/']").first
            href = link.get_attribute("href") or ""
            job_id = _job_id_from_href(href)
            if not job_id:
                continue
            title = ""
            for sel in (
                "h3.base-search-card__title",
                ".job-card-list__title--link strong",
                ".job-card-container__link strong",
                ".job-card-list__title--link",
            ):
                try:
                    t = card.locator(sel).first.inner_text().strip()
                    if t:
                        title = t
                        break
                except Exception:
                    pass
            if not title:
                try:
                    title = link.inner_text().strip()
                except Exception:
                    pass
            company = ""
            for sel in (
                ".base-search-card__subtitle",
                ".job-card-container__primary-description",
                ".artdeco-entity-lockup__subtitle",
            ):
                try:
                    c = card.locator(sel).first.inner_text().strip()
                    if c:
                        company = c
                        break
                except Exception:
                    pass
            location = ""
            for sel in (
                ".job-search-card__location",
                ".job-card-container__metadata-item",
                ".artdeco-entity-lockup__caption",
            ):
                try:
                    loc = card.locator(sel).first.inner_text().strip()
                    if loc:
                        location = loc
                        break
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
            if not easy:
                # Fallback: scan the whole card for an Easy Apply badge.
                try:
                    easy = "easy apply" in card.inner_text().lower()
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


def _save_results(all_jobs: dict[str, dict]) -> None:
    """Write the current results to RESULTS_FILE (incremental save).

    Called after each successful page so a partial/throttled search that
    gets killed (OOM, timeout) still produces usable jobs.
    """
    try:
        lines = []
        for j in all_jobs.values():
            lines.append(
                f"{j['id']} | {j['title']} | {j['company']} | {j['location']} | "
                f"{'EASY' if j['easy'] else 'EXTERNAL'} | {j['url']}"
            )
        RESULTS_FILE.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    fresh = "--fresh" in sys.argv
    if fresh:
        try:
            if RESULTS_FILE.exists():
                RESULTS_FILE.unlink()
        except OSError:
            pass

    all_jobs: dict[str, dict] = {}
    headless = "--headed" not in sys.argv

    def _proxy_kwargs() -> dict:
        """Residential proxy from env (LinkedIn blocks datacenter IPs).

        Set PROXY_URL (e.g. http://user:pass@host:port) on Render to route
        the browser through a residential IP. Empty -> no proxy.
        """
        url = os.environ.get("PROXY_URL", "").strip()
        if not url:
            return {}
        server = url.replace("http://", "").replace("https://", "")
        pw: dict = {"server": f"http://{server}"}
        if "@" in server:
            auth, host = server.split("@", 1)
            if ":" in auth:
                user, pwd = auth.split(":", 1)
                pw["username"] = user
                pw["password"] = pwd
        print(f"[search] using proxy: {pw['server']}", flush=True)
        return {"proxy": pw}

    def _launch():
        ctx = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            no_viewport=True,
            args=BROWSER_ARGS,
            **_proxy_kwargs(),
        )
        _inject_session(ctx)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        return ctx, pg

    with sync_playwright() as playwright:
        context, page = _launch()
        try:
            # LinkedIn throttles BURSTS from datacenter IPs. A single page load
            # works fine (verified via /probe), but firing 100+ page loads in a
            # row trips the rate limit and every subsequent load hangs, so the
            # search returns 0 jobs. To stay under the limit we:
            #   - cap the total number of page loads per search (max_pages),
            #   - stop early once we have enough unique jobs (target_jobs),
            #   - treat consecutive EMPTY pages as a throttle signal and abort,
            #   - pace requests human-like (4-8s) with a longer pause between
            #     different keyword searches.
            #
            # Memory: Render's free tier is 512MB shared with Flask + the
            # marathon. LinkedIn's heavy JS pages accumulate memory in the
            # browser, so we recycle (restart) the browser every few page
            # loads to keep the footprint flat.
            consecutive_failures = 0   # hard failures (exceptions / hung loads)
            consecutive_empty = 0      # pages that loaded but returned 0 jobs
            max_consecutive_failures = 3
            max_consecutive_empty = 4
            max_pages = 8              # hard cap on page loads per search
            target_jobs = 120          # stop once we have this many unique jobs
            pages_loaded = 0
            recycle_every = 6
            for keywords, location in SEARCHES:
                if pages_loaded >= max_pages:
                    print(f"[search] reached {max_pages}-page cap — stopping", flush=True)
                    break
                if len(all_jobs) >= target_jobs:
                    print(f"[search] have {len(all_jobs)} jobs (target {target_jobs}) — stopping", flush=True)
                    break
                if consecutive_failures >= max_consecutive_failures:
                    print(f"[search] {consecutive_failures} consecutive failures — aborting search early", flush=True)
                    break
                if consecutive_empty >= max_consecutive_empty:
                    print(f"[search] {consecutive_empty} empty pages in a row (likely throttled) — aborting", flush=True)
                    break
                for start in PAGE_STARTS:
                    if pages_loaded >= max_pages or len(all_jobs) >= target_jobs:
                        break
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
                        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        time.sleep(3)
                        scroll_to_load(page, rounds=3)
                        jobs = extract_jobs(page)
                        consecutive_failures = 0
                        pages_loaded += 1
                        if not jobs:
                            consecutive_empty += 1
                            print(f"[search] '{keywords}' @ {location} start={start}: 0 cards (empty {consecutive_empty} in a row)", flush=True)
                            break  # no more pages for this search
                        consecutive_empty = 0
                        added = 0
                        for j in jobs:
                            if j["id"] not in all_jobs:
                                all_jobs[j["id"]] = j
                                added += 1
                        print(f"[search] '{keywords}' @ {location} start={start}: {len(jobs)} cards (+{added} new, total {len(all_jobs)})", flush=True)
                        # Incremental save: persist results now so a partial
                        # search (killed by OOM/timeout) still yields jobs.
                        _save_results(all_jobs)
                        if len(jobs) < 10:
                            break  # last page
                    except Exception as exc:
                        consecutive_failures += 1
                        print(f"[search] '{keywords}' @ {location} start={start} FAILED ({consecutive_failures} in a row): {exc}", flush=True)
                        if consecutive_failures >= max_consecutive_failures:
                            break
                    # Human-like pacing: 3-6s between page loads.
                    time.sleep(random.uniform(3.0, 6.0))
                    # Recycle the browser to cap memory growth.
                    if pages_loaded and pages_loaded % recycle_every == 0:
                        try:
                            context.close()
                        except Exception:
                            pass
                        time.sleep(2)
                        context, page = _launch()
                        print(f"[search] recycled browser after {pages_loaded} pages", flush=True)
                # Longer pause between different keyword searches.
                time.sleep(random.uniform(8.0, 14.0))
        finally:
            try:
                context.close()
            except Exception:
                pass

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
