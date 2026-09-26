"""Git-Based Auto-Updater & Self-Healing Codebase Daemon.

Monitors the GitHub repository in the background, pulls remote updates/hotfixes,
updates dependencies silently, and signals the automation engine to reload.
Enables full remote management and bug-fixing from phone/browser without interrupting
the broader 24/7 marathon loop.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
UPDATE_LOG = HERE / ".git_update.log"

def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [git-updater] {msg}"
    print(line, flush=True)
    try:
        with UPDATE_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run_cmd(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd or PROJECT_ROOT),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def check_and_apply_updates(auto_install_deps: bool = True) -> bool:
    """Check for remote commits on GitHub. Pull and apply hotfix if available."""
    # Check if inside a git repository
    rc, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        return False

    # Fetch latest references from origin
    rc, fetch_out = run_cmd(["git", "fetch", "origin"])
    if rc != 0:
        # Network down or offline — skip gracefully
        return False

    # Compare local HEAD with remote HEAD
    rc, local_hash = run_cmd(["git", "rev-parse", "HEAD"])
    rc, remote_hash = run_cmd(["git", "rev-parse", "@{u}"])

    if rc != 0 or not local_hash or not remote_hash:
        return False

    if local_hash == remote_hash:
        # Codebase is fully up to date
        return False

    log(f"New update detected on GitHub: {local_hash[:7]} -> {remote_hash[:7]}")

    # Check which files changed before pulling
    rc, diff_files = run_cmd(["git", "diff", "--name-only", "HEAD", "@{u}"])

    # Pull latest commits with self-healing reset on conflict
    rc, pull_out = run_cmd(["git", "pull", "--ff-only"])
    if rc != 0:
        log(f"Fast-forward merge conflict, self-healing working tree...")
        run_cmd(["git", "reset", "--hard", "@{u}"])
        rc, pull_out = run_cmd(["git", "pull", "--no-rebase"])
        if rc != 0:
            log(f"Git pull error: {pull_out}")
            return False

    log(f"Successfully pulled latest code: {pull_out}")

    # Auto-update Python / Node dependencies if manifests were modified
    if auto_install_deps and diff_files:
        if "requirements.txt" in diff_files:
            log("requirements.txt changed; updating pip packages...")
            rc, pip_out = run_cmd([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
            log(f"pip install: {'success' if rc == 0 else pip_out[:200]}")

        if "package.json" in diff_files:
            log("package.json changed; updating npm packages...")
            run_cmd(["npm", "install"])

    log("Hotfix injection complete. Codebase is self-healed and updated.")
    return True


def watch_loop(poll_interval_seconds: int = 180) -> None:
    """Continuous background watcher daemon."""
    log(f"Git auto-updater started (polling every {poll_interval_seconds}s)...")
    while True:
        try:
            updated = check_and_apply_updates()
            if updated:
                log("Update applied. Signaling runners.")
        except Exception as exc:
            log(f"Watcher error: {exc}")
        time.sleep(poll_interval_seconds)


if __name__ == "__main__":
    if "--check" in sys.argv:
        has_update = check_and_apply_updates()
        print(f"Updated: {has_update}")
    else:
        watch_loop()
