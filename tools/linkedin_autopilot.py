"""Fully autonomous LinkedIn job application pipeline (headless).

Flow:
  1. Search LinkedIn for entry-level Easy Apply jobs (headless browser).
  2. Filter to relevant software-dev roles (SDE, full-stack, python, AI/ML,
     android, frontend, backend, java, react, ML, data).
  3. Skip jobs already applied to (tracked in tools/.applied_jobs.txt).
  4. Apply to each job via linkedin_apply.py logic (headless, auto-submit).
  5. Log results to tools/.autopilot_results.txt.

Usage:
    python tools/linkedin_autopilot.py [--max N] [--headed]

    --max N     Apply to at most N jobs this run (default 10).
    --headed    Show the browser window (debug only).
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS_FILE = HERE / ".search_results.txt"
APPLIED_FILE = HERE / ".applied_jobs.txt"
AUTOPILOT_LOG = HERE / ".autopilot_results.txt"
STATUS_FILE = HERE / ".apply_status.txt"
SEARCH_SCRIPT = HERE / "linkedin_search.py"
APPLY_SCRIPT = HERE / "linkedin_apply.py"
DEFAULT_RESUME = HERE.parent / "career-ops" / "output" / "cv-pragma-edge-trainee.pdf"

# Keywords that indicate a relevant software-dev role (case-insensitive).
# Every keyword must be dev-specific so roles like "Human Resources Intern"
# or "Marketing Trainee" never match.
RELEVANT_KEYWORDS = [
    "software engineer", "software developer", "software development",
    "sde", "full stack", "fullstack", "full-stack",
    "python developer", "python/django", "java developer", "java full stack",
    "java software", "backend developer", "back end developer", "backend engineer",
    "front end developer", "frontend developer", "front-end developer",
    "react developer", "react.js", "node.js", "nodejs",
    "android developer", "mobile developer", "mobile application",
    "flutter developer", "ios developer",
    "ai engineer", "ai software", "ai/ml", "ai-ml", "machine learning",
    "ml engineer", "ml intern", "genai", "gen ai", "llm",
    "data scientist", "data analyst", "data engineer",
    "application engineer", "application developer", "web developer",
    "django", "fastapi", "javascript developer", "typescript",
    "graduate trainee", "graduate software", "software intern",
    "developer intern", "engineering intern", "sde intern",
    "dotnet developer", ".net developer",
]

# Keywords that disqualify a role (non-dev or too senior).
EXCLUDE_KEYWORDS = [
    "copywriter", "video editor", "social media", "marketing",
    "human resources", "hr intern", "recruiter", "talent",
    "trainer", "labeling", "quality analyst", "performance analyst",
    "hr data", "marketo", "defi quant", "sounding rockets", "ham radio",
    "sr. associate", "senior", "lead ", "staff ", "principal", "manager",
    "director", "architect", "4+yrs", "5+ years", "3+ years", "4+ years",
    "content writer", "graphic design", "ui/ux design", "business analyst",
    "sales", "operations", "customer support", "bali",
]

# Preferred locations (order = priority). Jobs outside these are still
# applied to if remote/India-wide, but deprioritized.
PREFERRED_LOCATIONS = ["mysore", "bengaluru", "bangalore", "remote", "india"]


def is_relevant(title: str) -> bool:
    t = title.lower()
    if any(k in t for k in EXCLUDE_KEYWORDS):
        return False
    return any(k in t for k in RELEVANT_KEYWORDS)


def location_score(location: str) -> int:
    loc = location.lower()
    for i, pref in enumerate(PREFERRED_LOCATIONS):
        if pref in loc:
            return 100 - i * 10
    return 0


def load_applied() -> set[str]:
    if APPLIED_FILE.exists():
        return set(APPLIED_FILE.read_text(encoding="utf-8").split())
    return set()


def mark_applied(job_id: str) -> None:
    with APPLIED_FILE.open("a", encoding="utf-8") as f:
        f.write(job_id + "\n")


BATCH_URLS_FILE = HERE / ".batch_urls.txt"
BATCH_RESULTS_FILE = HERE / ".batch_results.txt"


def run_batch(job_urls: list[str], resume: Path, headed: bool) -> dict[str, str]:
    """Run linkedin_apply.py --batch once for all jobs (single browser session).
    Returns {job_url: status}."""
    BATCH_URLS_FILE.write_text("\n".join(job_urls), encoding="utf-8")
    try:
        if BATCH_RESULTS_FILE.exists():
            BATCH_RESULTS_FILE.unlink()
    except OSError:
        pass
    cmd = [sys.executable, str(APPLY_SCRIPT), "--batch", str(BATCH_URLS_FILE),
           str(resume), "--submit", "--autonomous"]
    if headed:
        cmd.append("--headed")
    try:
        proc = subprocess.run(cmd, cwd=str(HERE.parent),
                              timeout=180 + 90 * len(job_urls),
                              capture_output=True, text=True)
        print(proc.stdout[-3000:] if proc.stdout else "", flush=True)
    except subprocess.TimeoutExpired:
        print("[autopilot] batch timed out", flush=True)
    results: dict[str, str] = {}
    if BATCH_RESULTS_FILE.exists():
        for line in BATCH_RESULTS_FILE.read_text(encoding="utf-8").splitlines():
            if " | " in line:
                # Split from the LEFT: the URL never contains ' | ', but the
                # status text may (dialog excerpts use ' | ' separators).
                url, st = line.split(" | ", 1)
                results[url.strip()] = st.strip()
    return results


def main() -> int:
    max_jobs = 10
    headed = "--headed" in sys.argv
    if "--max" in sys.argv:
        idx = sys.argv.index("--max")
        if idx + 1 < len(sys.argv):
            max_jobs = int(sys.argv[idx + 1])

    # Step 1: fresh search.
    print("[autopilot] searching for jobs...", flush=True)
    subprocess.run([sys.executable, str(SEARCH_SCRIPT)] + (["--headed"] if headed else []),
                   cwd=str(HERE.parent), timeout=600)

    if not RESULTS_FILE.exists():
        print("[autopilot] no search results file", flush=True)
        return 1

    # Step 2: parse + filter.
    applied = load_applied()
    candidates = []
    for line in RESULTS_FILE.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        # Titles may contain '|', so parse fixed fields from both ends.
        job_id = parts[0]
        url = parts[-1]
        easy = parts[-2]
        location = parts[-3]
        company = parts[-4]
        title = " | ".join(parts[1:-4])
        if easy != "EASY":
            continue
        if job_id in applied:
            continue
        if not is_relevant(title):
            continue
        candidates.append({
            "id": job_id, "title": title, "company": company,
            "location": location, "url": url,
            "score": location_score(location),
        })

    # Sort: preferred locations first.
    candidates.sort(key=lambda c: -c["score"])
    print(f"[autopilot] {len(candidates)} relevant Easy Apply candidates", flush=True)

    # Step 3: apply — one batched browser session for all jobs (fast).
    batch = candidates[:max_jobs]
    print(f"[autopilot] applying to {len(batch)} jobs in one session...", flush=True)
    for c in batch:
        print(f"[autopilot]   queued: {c['title']} @ {c['company']} ({c['location']})", flush=True)
    statuses = run_batch([c["url"] for c in batch], DEFAULT_RESUME, headed)

    results = []
    applied_count = 0
    for c in batch:
        status = statuses.get(c["url"], "UNKNOWN")
        print(f"[autopilot] {c['title']} @ {c['company']} -> {status}", flush=True)
        results.append(f"{c['id']} | {c['title']} | {c['company']} | {c['location']} | {status}")
        if status.startswith("DONE"):
            mark_applied(c["id"])
            applied_count += 1
        elif status.startswith("NEED_INPUT"):
            results[-1] += " (skipped-stuck)"

    # Step 4: write results.
    with AUTOPILOT_LOG.open("a", encoding="utf-8") as f:
        f.write(f"\n=== run {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        for r in results:
            f.write(r + "\n")

    print(f"[autopilot] done: {applied_count} applications submitted", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
