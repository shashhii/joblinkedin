"""Autonomous LinkedIn application marathon — target: 100 submissions.

Runs unattended in a loop. No browser window, no permission prompts:

  1. COUNT submissions already made (tools/.applied_jobs.txt).
  2. If the job list is missing or older than 1 hour, DELETE it and extract a
     FRESH list from LinkedIn (new job IDs -> no 'job does not exist' errors).
     The tried-jobs list is reset on each refresh so transient failures get
     one retry with the fresh list.
  3. Filter relevant entry-level Easy Apply dev roles, skip applied/tried.
  4. Apply in one headless batched browser session (up to BATCH_SIZE jobs).
  5. Log everything; sleep briefly; repeat until TARGET is reached.

Usage:
    python tools/linkedin_marathon.py [--target 100] [--headed]

Files (inside tools/):
    .applied_jobs.txt      one job id per line, appended on each DONE submit
    .tried_jobs.txt        every attempted job id (reset on hourly refresh)
    .marathon_status.txt   live progress summary
    .marathon_log.txt      full step-by-step log
    .autopilot_results.txt per-job results history
"""

from __future__ import annotations

import os
import random
import signal
import subprocess
import sys
import time
from pathlib import Path

# Optional AI workflow monitor (Gemini/Grok). Degrades gracefully when no
# API key is configured in tools/.ai.env.
try:
    import ai_assist
except Exception:
    ai_assist = None

# Optional R2 session sync (Render has no persistent disk). Degrades
# gracefully when R2 credentials are not configured (local runs).
try:
    import r2_sync
except Exception:
    r2_sync = None

HERE = Path(__file__).resolve().parent
RESULTS_FILE = HERE / ".search_results.txt"
APPLIED_FILE = HERE / ".applied_jobs.txt"
TRIED_FILE = HERE / ".tried_jobs.txt"
STATUS_FILE = HERE / ".marathon_status.txt"
MARATHON_LOG = HERE / ".marathon_log.txt"
RESULTS_LOG = HERE / ".autopilot_results.txt"
SEARCH_SCRIPT = HERE / "linkedin_search.py"
APPLY_SCRIPT = HERE / "linkedin_apply.py"
BATCH_URLS_FILE = HERE / ".batch_urls.txt"
BATCH_RESULTS_FILE = HERE / ".batch_results.txt"
LOCK_FILE = HERE / ".marathon.lock"
# Default resume. The bundled copy (tools/resume/) ships with the repo so it
# exists on Render; the career-ops path is the local-machine fallback.
_BUNDLED_RESUME = HERE / "resume" / "cv-pragma-edge-trainee.pdf"
_CAREEROPS_RESUME = HERE.parent / "career-ops" / "output" / "cv-pragma-edge-trainee.pdf"
DEFAULT_RESUME = _BUNDLED_RESUME if _BUNDLED_RESUME.exists() else _CAREEROPS_RESUME

TARGET_DEFAULT = 100
REFRESH_SECONDS = 3600          # delete + re-extract the job list every hour
EXHAUSTED_COOLDOWN = 900        # pool empty -> early refresh after 15 min cooldown
BATCH_SIZE = 8                  # jobs per browser session (smaller = less rate-limiting)
INTER_BATCH_PAUSE = 120         # seconds between batches (anti-rate-limit)
# Account safety: hard cap on applications per local day. Override with the
# DAILY_CAP env var on Render. 25/day is a conservative, low-risk volume.
DAILY_CAP = int(os.environ.get("DAILY_CAP", "25"))
DAILY_COUNT_FILE = HERE / ".daily_count.txt"
# When LinkedIn bounces us to the authwall, wait this long for a fresh
# session to be restored from R2 before retrying.
SESSION_EXPIRED_COOLDOWN = 1800

# Dev-specific role keywords (same curated set as the autopilot).
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
    "dotnet developer", ".net developer", "associate software",
    "junior software", "qa engineer", "devops", "golang", "node-js",
]

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

PREFERRED_LOCATIONS = ["mysore", "bengaluru", "bangalore", "remote", "india"]


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(f"[marathon] {msg}", flush=True)
    try:
        with MARATHON_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def write_status(applied: int, target: int, note: str) -> None:
    try:
        STATUS_FILE.write_text(
            f"applied: {applied}/{target}\n"
            f"updated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"note: {note}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def count_applied() -> int:
    if not APPLIED_FILE.exists():
        return 0
    return len([x for x in APPLIED_FILE.read_text(encoding="utf-8").split() if x])


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def daily_submitted() -> int:
    """Applications submitted on the current local day (0 if none/other day)."""
    try:
        parts = DAILY_COUNT_FILE.read_text(encoding="utf-8").split()
        if parts and parts[0] == _today():
            return int(parts[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def bump_daily(n: int = 1) -> None:
    """Record n more applications submitted today (resets on a new day)."""
    day = _today()
    cur = 0
    try:
        parts = DAILY_COUNT_FILE.read_text(encoding="utf-8").split()
        if parts and parts[0] == day:
            cur = int(parts[1])
    except (OSError, ValueError, IndexError):
        pass
    try:
        DAILY_COUNT_FILE.write_text(f"{day} {cur + n}", encoding="utf-8")
    except OSError:
        pass


def wait_until_next_day() -> None:
    """Sleep until ~00:05 the next local day (used after hitting the cap)."""
    now = time.localtime()
    next_day = time.mktime((now.tm_year, now.tm_mon, now.tm_mday + 1,
                            0, 5, 0, 0, 0, -1))
    secs = max(60, int(next_day - time.time()))
    log(f"daily cap {DAILY_CAP} reached; resting {secs // 3600}h until next day")
    time.sleep(secs)


def r2_restore() -> None:
    """Pull the latest LinkedIn session from R2 (no-op without credentials)."""
    if r2_sync is None:
        return
    try:
        if r2_sync.restore_session():
            log("R2: restored LinkedIn session from cloud")
    except Exception as exc:
        log(f"R2 restore error: {exc.__class__.__name__}")


def r2_upload() -> None:
    """Push the current LinkedIn session to R2 (no-op without credentials)."""
    if r2_sync is None:
        return
    try:
        if r2_sync.upload_session():
            log("R2: uploaded LinkedIn session to cloud")
    except Exception as exc:
        log(f"R2 upload error: {exc.__class__.__name__}")


def load_ids(path: Path) -> set[str]:
    if path.exists():
        return {x for x in path.read_text(encoding="utf-8").split() if x}
    return set()


def mark_id(path: Path, job_id: str) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(job_id + "\n")


def _pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is currently running."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=10,
            ).stdout
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


def _try_create_lock() -> bool:
    """Atomically create the lock file. Returns True if we got it."""
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        return True
    except FileExistsError:
        return False
    except OSError:
        return False


def acquire_lock() -> bool:
    """Single-instance guard. Returns False if another live marathon holds the lock.

    Two marathon instances launching Chromium on the same profile corrupt the
    session (Easy Apply modal stops rendering), so only one may run at a time.
    Uses an atomic O_CREAT|O_EXCL create so two starters cannot both win.
    """
    if _try_create_lock():
        return True
    # Lock exists: check whether the holder is still alive.
    try:
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip() or "0")
    except (ValueError, OSError):
        pid = 0
    if pid and _pid_alive(pid):
        log(f"another marathon is already running (pid {pid}); exiting to avoid "
            "double-launching the browser on the same profile")
        return False
    # Stale lock from a dead process: remove and retry the atomic create once.
    try:
        LOCK_FILE.unlink()
    except OSError:
        return False
    return _try_create_lock()


def release_lock() -> None:
    try:
        if LOCK_FILE.exists() and LOCK_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK_FILE.unlink()
    except OSError:
        pass


def results_age_seconds() -> float:
    if not RESULTS_FILE.exists():
        return float("inf")
    return time.time() - RESULTS_FILE.stat().st_mtime


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


def parse_candidates(applied: set[str], tried: set[str]) -> list[dict]:
    candidates = []
    if not RESULTS_FILE.exists():
        return candidates
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
        if job_id in applied or job_id in tried:
            continue
        if not is_relevant(title):
            continue
        candidates.append({
            "id": job_id, "title": title, "company": company,
            "location": location, "url": url,
            "score": location_score(location),
        })
    candidates.sort(key=lambda c: -c["score"])
    return candidates


def do_refresh(headed: bool, reason: str) -> bool:
    """Delete the old job list + tried list, extract a fresh one (new IDs)."""
    log(f"refresh ({reason}): deleting old job list, extracting fresh jobs...")
    try:
        if TRIED_FILE.exists():
            TRIED_FILE.unlink()  # reset retries with the fresh list
    except OSError:
        pass
    return fresh_search(headed)


def fresh_search(headed: bool) -> bool:
    """Delete the old list and extract a fresh one (new job IDs)."""
    log("extracting fresh jobs from LinkedIn...")
    cmd = [sys.executable, str(SEARCH_SCRIPT), "--fresh"]
    if headed:
        cmd.append("--headed")
    timed_out = False
    try:
        # start_new_session=True puts the search in its own process group so
        # we can kill the WHOLE tree (Python + Chromium) on timeout. Without
        # this, a timed-out search leaves orphaned Chromium running, which
        # leaks memory and OOM-kills the Render service (512MB limit).
        proc = subprocess.Popen(
            cmd, cwd=str(HERE.parent),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            proc.communicate(timeout=1800)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError, AttributeError):
                proc.kill()
            proc.wait()
            log("search timed out (killed process tree)")
            timed_out = True
    except Exception as exc:
        log(f"search failed: {exc}")
        return False
    # Count jobs even on timeout: the search saves results incrementally
    # after each page, so a partial/throttled search still yields usable jobs.
    n = 0
    if RESULTS_FILE.exists():
        n = len([x for x in RESULTS_FILE.read_text(encoding="utf-8").splitlines() if x])
    if timed_out:
        log(f"search timed out but {n} jobs were saved incrementally")
    else:
        log(f"fresh search done: {n} jobs in list")
    return n > 0


def run_batch(job_urls: list[str], resume: Path, headed: bool) -> dict[str, str]:
    """One headless browser session applies to all jobs in the batch."""
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
                              timeout=180 + 100 * len(job_urls),
                              capture_output=True, text=True)
        if proc.stdout:
            for line in proc.stdout.splitlines():
                if line.startswith("[batch]"):
                    log(line)
    except subprocess.TimeoutExpired:
        log("batch timed out")
    results: dict[str, str] = {}
    if BATCH_RESULTS_FILE.exists():
        for line in BATCH_RESULTS_FILE.read_text(encoding="utf-8").splitlines():
            if " | " in line:
                # Split from the LEFT: URLs never contain ' | ', statuses may.
                url, st = line.split(" | ", 1)
                results[url.strip()] = st.strip()
    return results


def ai_monitor_report() -> None:
    """Ask the AI to analyze the pipeline health and log its report."""
    if ai_assist is None or not ai_assist.ai_available():
        return
    try:
        status_text = STATUS_FILE.read_text(encoding="utf-8") if STATUS_FILE.exists() else ""
        log_tail = MARATHON_LOG.read_text(encoding="utf-8")[-3000:] if MARATHON_LOG.exists() else ""
        results_tail = ""
        if RESULTS_LOG.exists():
            results_tail = RESULTS_LOG.read_text(encoding="utf-8")[-2000:]
        report = ai_assist.monitor_workflow(status_text, log_tail, results_tail)
        if report:
            log("AI MONITOR REPORT:\n" + report)
    except Exception as exc:
        log(f"ai monitor error: {exc.__class__.__name__}")


def main() -> int:
    target = TARGET_DEFAULT
    if "--target" in sys.argv:
        idx = sys.argv.index("--target")
        if idx + 1 < len(sys.argv):
            target = int(sys.argv[idx + 1])
    headed = "--headed" in sys.argv

    if not acquire_lock():
        return 1

    log(f"=== marathon start: target {target} applications (already applied: {count_applied()}) ===")

    # Render has no persistent disk: restore the LinkedIn session from R2 so
    # a fresh container can pick up where the last one left off.
    r2_restore()

    try:
        while True:
            applied_count = count_applied()
            if applied_count >= target:
                log(f"TARGET REACHED: {applied_count}/{target} applications submitted")
                write_status(applied_count, target, "target reached")
                break

            # Hourly refresh: delete old IDs, extract a fresh list.
            if results_age_seconds() >= REFRESH_SECONDS:
                do_refresh(headed, "hourly")

            applied = load_ids(APPLIED_FILE)
            tried = load_ids(TRIED_FILE)
            candidates = parse_candidates(applied, tried)
            log(f"{len(candidates)} fresh candidates (applied so far: {len(applied)}/{target})")

            if not candidates:
                # Pool exhausted: brief cooldown, then early refresh with a
                # brand-new job list (hourly cadence stays the max list age).
                write_status(len(applied), target,
                             "pool exhausted; early refresh after 15 min cooldown")
                log(f"pool exhausted; cooling down {EXHAUSTED_COOLDOWN // 60} min "
                    "before early refresh")
                time.sleep(EXHAUSTED_COOLDOWN)
                if count_applied() >= target:
                    continue
                do_refresh(headed, "pool exhausted")
                continue

            # Daily application cap (account safety): rest until next day.
            if daily_submitted() >= DAILY_CAP:
                write_status(len(applied), target,
                             f"daily cap {DAILY_CAP} reached; resting until next day")
                wait_until_next_day()
                continue

            batch = candidates[:BATCH_SIZE]
            for c in batch:
                log(f"  queued: {c['title']} @ {c['company']} ({c['location']})")
            write_status(len(applied), target, f"applying to batch of {len(batch)}")
            statuses = run_batch([c["url"] for c in batch], DEFAULT_RESUME, headed)

            # Session expired: LinkedIn bounced us to the authwall. Stop
            # applying, try to pull a fresh session from R2, then wait.
            if any(st == "FAILED:session-expired" for st in statuses.values()):
                write_status(count_applied(), target,
                             "SESSION EXPIRED - waiting for fresh session from R2")
                log(f"SESSION EXPIRED: authwall detected; pausing "
                    f"{SESSION_EXPIRED_COOLDOWN // 60} min for a fresh session")
                r2_restore()
                time.sleep(SESSION_EXPIRED_COOLDOWN)
                continue

            submitted_now = 0
            history = [f"\n=== marathon {time.strftime('%Y-%m-%d %H:%M:%S')} ==="]
            for c in batch:
                st = statuses.get(c["url"], "UNKNOWN")
                mark_id(TRIED_FILE, c["id"])
                if st.startswith("DONE"):
                    mark_id(APPLIED_FILE, c["id"])
                    submitted_now += 1
                log(f"  {c['title']} @ {c['company']} -> {st}")
                history.append(
                    f"{c['id']} | {c['title']} | {c['company']} | {c['location']} | {st}"
                )
            try:
                with RESULTS_LOG.open("a", encoding="utf-8") as f:
                    f.write("\n".join(history) + "\n")
            except OSError:
                pass

            total = count_applied()
            log(f"batch done: +{submitted_now} submitted (total {total}/{target})")
            write_status(total, target, "between batches")
            if submitted_now:
                bump_daily(submitted_now)
            # Persist the session to R2 so the next Render boot can resume.
            r2_upload()
            ai_monitor_report()
            if total >= target:
                log(f"TARGET REACHED: {total}/{target} applications submitted")
                break

            # Polite pause with jitter before the next batch.
            pause = INTER_BATCH_PAUSE + random.uniform(0, 20)
            time.sleep(pause)
    except KeyboardInterrupt:
        log(f"marathon stopped by user at {count_applied()}/{target}")
        write_status(count_applied(), target, "stopped by user")
        return 1
    finally:
        release_lock()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
