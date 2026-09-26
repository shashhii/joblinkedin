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

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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


def _profile_has_valid_session(context) -> bool:
    """True if the persistent profile already holds a live LinkedIn login.

    Locally the profile keeps a valid ``li_at`` token across runs. Injecting
    the (possibly stale) R2 cookie file on top of it *replaces* ``li_at`` with
    an older token and LinkedIn invalidates the session, bouncing us to the
    login page. So when the profile is already logged in we must NOT inject.
    On Render the profile is empty, so this returns False and injection
    proceeds as before.
    """
    try:
        import time as _time
        for c in context.cookies("https://www.linkedin.com"):
            if c.get("name") == "li_at" and c.get("value"):
                exp = c.get("expires", -1)
                if exp == -1 or exp > _time.time():
                    return True
    except Exception:
        pass
    return False


def _inject_session(context) -> None:
    """Best-effort: inject LinkedIn cookies from tools/.session/cookies.json.

    On Render the persistent profile is empty, so the login comes from the
    R2-restored cookie file. Locally the profile already holds a valid
    session, so we skip injection (overwriting it with stale R2 cookies would
    invalidate the login). Never raises.
    """
    try:
        if _profile_has_valid_session(context):
            print("[search] profile already logged in — skipping cookie injection", flush=True)
            return
        import r2_sync
        cookies = r2_sync.load_cookies()
        if cookies:
            context.add_cookies(cookies)
            print(f"[search] injected {len(cookies)} session cookies", flush=True)
    except Exception as exc:
        print(f"[search] cookie inject skipped: {exc.__class__.__name__}", flush=True)

# (keywords, location) — entry/associate + Easy Apply filters applied in URL.
SEARCHES = [
    # Bengaluru Hub
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
    ("web developer", "Bengaluru"),
    ("AI engineer", "Bengaluru"),
    ("cloud engineer", "Bengaluru"),
    ("mobile developer", "Bengaluru"),
    ("qa automation", "Bengaluru"),
    ("flutter developer", "Bengaluru"),
    ("react native", "Bengaluru"),
    # Mysore & Karnataka Hubs
    ("software developer", "Mysore"),
    ("software engineer", "Mysore"),
    ("python developer", "Mysore"),
    ("web developer", "Mysore"),
    # Hyderabad Hub
    ("software engineer", "Hyderabad"),
    ("full stack developer", "Hyderabad"),
    ("python developer", "Hyderabad"),
    ("java developer", "Hyderabad"),
    ("react developer", "Hyderabad"),
    ("data engineer", "Hyderabad"),
    ("data analyst", "Hyderabad"),
    ("AI engineer", "Hyderabad"),
    # Pune Hub
    ("software developer", "Pune"),
    ("python developer", "Pune"),
    ("full stack developer", "Pune"),
    ("react developer", "Pune"),
    ("java developer", "Pune"),
    ("data analyst", "Pune"),
    # Chennai & Coimbatore
    ("software engineer", "Chennai"),
    ("python developer", "Chennai"),
    ("full stack developer", "Chennai"),
    ("web developer", "Chennai"),
    # Delhi NCR / Noida / Gurgaon
    ("software developer", "Noida"),
    ("software engineer", "Gurugram"),
    ("python developer", "Noida"),
    ("full stack developer", "Gurugram"),
    ("react developer", "Noida"),
    # Mumbai & Maharashtra
    ("software engineer", "Mumbai"),
    ("full stack developer", "Mumbai"),
    ("python developer", "Mumbai"),
    # Remote / India-wide
    ("AI engineer", "India"),
    ("prompt engineer", "India"),
    ("gen ai engineer", "India"),
    ("frontend developer", "India"),
    ("react developer", "India"),
    ("backend developer", "India"),
    ("full stack developer", "India"),
    ("python developer", "India"),
    ("django developer", "India"),
    ("fastapi developer", "India"),
    ("node.js developer", "India"),
    ("golang developer", "India"),
    ("dotnet developer", "India"),
    ("qa engineer", "India"),
    ("software engineer", "India"),
    ("data analyst", "India"),
    ("data engineer", "India"),
    ("web developer", "India"),
    ("flutter developer", "India"),
    ("intern software", "India"),
    ("graduate engineer trainee", "India"),
    ("associate software engineer", "India"),
    ("junior developer", "India"),
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


def _first_text(scope, sel: str) -> str:
    """Return the first matching element's text, or '' if none.

    Uses a non-waiting ``count()`` check first so a selector that does not
    exist in the current DOM returns instantly instead of blocking on the
    default 30s locator timeout (which is what made extraction hang on
    LinkedIn's new AI-powered search UI).
    """
    try:
        loc = scope.locator(sel)
        if loc.count() > 0:
            return loc.first.inner_text(timeout=2000).strip()
    except Exception:
        pass
    return ""


def extract_jobs(page) -> list[dict]:
    """Extract job cards from the current search results page.

    LinkedIn's DOM changes over time. The current (2026) card container is
    ``div.job-search-card`` and the job link is a slug URL. The older
    selectors are kept as fallbacks so a future DOM change degrades
    gracefully instead of silently returning 0 jobs.

    All sub-selector reads are non-waiting (see ``_first_text``) so a DOM
    change can never stall the whole search on 30s locator timeouts.
    """
    jobs = []
    cards = page.locator(
        "div.job-search-card, div.job-card-container, li.jobs-search-results__list-item"
    ).all()
    for card in cards:
        try:
            link_loc = card.locator("a[href*='/jobs/view/']")
            if link_loc.count() == 0:
                continue
            link = link_loc.first
            href = link.get_attribute("href", timeout=2000) or ""
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
                title = _first_text(card, sel)
                if title:
                    break
            if not title:
                title = _first_text(card, "a[href*='/jobs/view/']")
            company = ""
            for sel in (
                ".base-search-card__subtitle",
                ".job-card-container__primary-description",
                ".artdeco-entity-lockup__subtitle",
            ):
                company = _first_text(card, sel)
                if company:
                    break
            location = ""
            for sel in (
                ".job-search-card__location",
                ".job-card-container__metadata-item",
                ".artdeco-entity-lockup__caption",
            ):
                location = _first_text(card, sel)
                if location:
                    break
            easy = False
            badge = _first_text(
                card,
                ".job-card-container__apply-method, .jobs-universal-applied-link, "
                "[class*='easy-apply'], .job-card-container__footer-wrapper",
            )
            if badge:
                easy = "easy apply" in badge.lower()
            if not easy:
                try:
                    easy = card.locator(
                        "button[aria-label*='Easy Apply'], a[aria-label*='Easy Apply']"
                    ).count() > 0
                except Exception:
                    pass
            if not easy:
                # Fallback: scan the whole card for an Easy Apply badge.
                try:
                    easy = "easy apply" in card.inner_text(timeout=2000).lower()
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

        Set PROXY_URL on Render to route the browser through a residential IP.
        Supports http://, https:// and socks5:// schemes (the scheme is
        preserved, so Webshare's socks5:// endpoint works). Empty -> no proxy.
        """
        url = os.environ.get("PROXY_URL", "").strip()
        if not url:
            return {}
        if "://" in url:
            scheme, rest = url.split("://", 1)
        else:
            scheme, rest = "http", url
        pw: dict = {"server": f"{scheme}://{rest}"}
        if "@" in rest:
            auth, _host = rest.split("@", 1)
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
        # Cap any single Playwright operation at 30s so a frozen page
        # can't hang the whole search process forever.
        pg.set_default_timeout(30_000)
        pg.set_default_navigation_timeout(30_000)
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
            max_pages = 30             # expanded cap for fast continuous application
            target_jobs = 200          # collect up to 200 unique jobs per search
            pages_loaded = 0
            recycle_every = 8
            search_list = list(SEARCHES)
            random.shuffle(search_list)
            for keywords, location in search_list:
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
                        print(f"[search] goto: {url[:90]}", flush=True)
                        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        print(f"[search] loaded: {page.url[:90]}", flush=True)
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
