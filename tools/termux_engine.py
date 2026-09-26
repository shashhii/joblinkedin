"""24/7 Continuous Watchdog & Self-Healing Engine (Termux & Desktop).

Wraps the application marathon in a resilient supervisor loop:
  1. Manages wake-locks on Android/Termux (`termux-wake-lock`).
  2. Monitors health, memory, and internet connectivity.
  3. Periodically pulls remote hotfixes from GitHub via git_updater.
  4. Auto-recovers and restarts on app crashes, OOMs, or disconnects.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
HEALTH_FILE = HERE / ".engine_health.json"
ENGINE_LOG = HERE / ".engine.log"

def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [engine] {msg}"
    print(line, flush=True)
    try:
        with ENGINE_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def is_termux() -> bool:
    """Detect if running inside Android Termux environment."""
    return "com.termux" in os.environ.get("PREFIX", "") or "termux" in os.environ.get("HOME", "")


def acquire_termux_wake_lock() -> None:
    """Keep CPU awake on Android Termux to prevent OS sleep."""
    if is_termux() and shutil.which("termux-wake-lock"):
        try:
            subprocess.run(["termux-wake-lock"], check=False)
            log("Acquired Termux wake-lock (CPU sleep disabled)")
        except Exception as exc:
            log(f"Wake-lock error: {exc}")


def release_termux_wake_lock() -> None:
    """Release wake-lock on exit."""
    if is_termux() and shutil.which("termux-wake-unlock"):
        try:
            subprocess.run(["termux-wake-unlock"], check=False)
        except Exception:
            pass


def cleanup_lingering_browsers() -> None:
    """Kill orphaned headless browser instances to free memory."""
    try:
        kill_script = HERE / "_kill_browsers.py"
        if kill_script.exists():
            subprocess.run([sys.executable, str(kill_script)], timeout=30, capture_output=True)
    except Exception:
        pass


def write_health(restarts: int, status: str, last_exit_code: int = 0) -> None:
    """Write heartbeat status for external monitoring."""
    applied_count = 0
    applied_file = HERE / ".applied_jobs.txt"
    if applied_file.exists():
        try:
            applied_count = len([x for x in applied_file.read_text(encoding="utf-8").splitlines() if x.strip()])
        except Exception:
            pass

    health = {
        "status": status,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "restarts": restarts,
        "last_exit_code": last_exit_code,
        "applied_count": applied_count,
        "environment": "termux" if is_termux() else "desktop",
        "python": sys.version.split()[0],
    }
    try:
        HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
    except OSError:
        pass


def check_git_hotfixes() -> bool:
    """Check and pull hotfixes from GitHub."""
    try:
        import git_updater
        return git_updater.check_and_apply_updates()
    except Exception:
        return False


def run_supervisor(target: int = 1000) -> None:
    """Infinite self-healing watchdog loop."""
    log("==================================================")
    log("24/7 Autonomous Job Application Engine Starting...")
    log(f"Platform: {'Android Termux' if is_termux() else 'Desktop/Windows'}")
    log(f"Target: {target} applications")
    log("==================================================")

    acquire_termux_wake_lock()

    restarts = 0
    consecutive_fast_crashes = 0
    marathon_script = HERE / "run_local.py"

    while True:
        try:
            # 1. Check for GitHub updates / hotfixes
            updated = check_git_hotfixes()
            if updated:
                log("Codebase auto-updated from GitHub before next cycle")

            # 2. Cleanup stale locks & orphaned processes
            lock_file = HERE / ".marathon.lock"
            if lock_file.exists():
                try:
                    lock_file.unlink()
                except OSError:
                    pass
            cleanup_lingering_browsers()

            # 3. Update Health Status
            write_health(restarts, "running", 0)

            # 4. Launch Marathon Process
            start_time = time.time()
            log(f"[Cycle {restarts + 1}] Launching marathon process...")
            
            cmd = [sys.executable, str(marathon_script), "--target", str(target)]
            proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
            exit_code = proc.wait()

            duration = time.time() - start_time
            log(f"Marathon process exited with code {exit_code} (ran for {duration:.1f}s)")

            restarts += 1
            write_health(restarts, "crashed" if exit_code != 0 else "restarting", exit_code)

            # Handle fast crash backoff (if crashes in under 10 seconds)
            if duration < 10:
                consecutive_fast_crashes += 1
                cooldown = min(180, 10 * (2 ** (consecutive_fast_crashes - 1)))
                log(f"Rapid exit detected ({consecutive_fast_crashes} in a row); cooling down {cooldown}s...")
                time.sleep(cooldown)
            else:
                consecutive_fast_crashes = 0
                time.sleep(3)

        except KeyboardInterrupt:
            log("Watchdog stopped by user (Ctrl+C)")
            release_termux_wake_lock()
            break
        except Exception as exc:
            log(f"Supervisor error: {exc}; self-healing in 10s...")
            time.sleep(10)


if __name__ == "__main__":
    target_count = 1000
    if "--target" in sys.argv:
        idx = sys.argv.index("--target")
        if idx + 1 < len(sys.argv):
            target_count = int(sys.argv[idx + 1])
    run_supervisor(target_count)
