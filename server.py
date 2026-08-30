"""Render entry point: Flask health endpoint + marathon supervisor.

Render runs this as a web service (so the CF Worker keep-alive has something
to ping). It:

  * serves GET /health  -> JSON status (progress, session, uptime, cap)
  * serves GET /        -> tiny human-readable status page
  * spawns tools/linkedin_marathon.py as a child process and restarts it if
    it crashes (the marathon itself holds the single-instance lock, so a
    stale child can never double-apply)

Env vars (Render dashboard):
    PORT            set by Render automatically
    DAILY_CAP       applications per day (default 25)
    MARATHON_TARGET total applications (default 100)
    R2_*            Cloudflare R2 credentials (see tools/r2_sync.py)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from flask import Flask, jsonify

HERE = Path(__file__).resolve().parent
TOOLS = HERE / "tools"
STATUS_FILE = TOOLS / ".marathon_status.txt"
MARATHON_LOG = TOOLS / ".marathon_log.txt"
APPLIED_FILE = TOOLS / ".applied_jobs.txt"

app = Flask(__name__)

START_TIME = time.time()
_proc: subprocess.Popen | None = None
_proc_started = 0.0
_restarts = 0


# ---------------------------------------------------------------------------
# Marathon supervisor
# ---------------------------------------------------------------------------

def _spawn_marathon() -> subprocess.Popen:
    global _proc, _proc_started, _restarts
    target = os.environ.get("MARATHON_TARGET", "100")
    cmd = [sys.executable, str(TOOLS / "linkedin_marathon.py"),
           "--target", target]
    _proc = subprocess.Popen(
        cmd,
        cwd=str(HERE),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _proc_started = time.time()
    if _restarts:
        _log(f"marathon restarted (pid {_proc.pid}, restart #{_restarts})")
    else:
        _log(f"marathon started (pid {_proc.pid}, target {target})")
    return _proc


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(f"[server] {msg}", flush=True)
    try:
        with (TOOLS / ".server_log.txt").open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _reap() -> None:
    """Restart the marathon if it has exited (crash or target reached)."""
    global _proc, _restarts
    if _proc is None:
        return
    rc = _proc.poll()
    if rc is None:
        return
    _proc = None
    if rc == 0:
        _log(f"marathon exited cleanly (target reached); not restarting")
        return
    _restarts += 1
    _log(f"marathon exited rc={rc}; restarting in 30s")
    time.sleep(30)
    _spawn_marathon()


def _read_status() -> dict:
    out = {"applied": None, "target": None, "note": "", "updated": ""}
    try:
        for line in STATUS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("applied:"):
                a, _, t = line.split(":", 1)[1].strip().partition("/")
                out["applied"] = int(a)
                out["target"] = int(t)
            elif line.startswith("updated:"):
                out["updated"] = line.split(":", 1)[1].strip()
            elif line.startswith("note:"):
                out["note"] = line.split(":", 1)[1].strip()
    except (OSError, ValueError):
        pass
    return out


def _count_applied() -> int:
    if not APPLIED_FILE.exists():
        return 0
    return len([x for x in APPLIED_FILE.read_text(encoding="utf-8").split() if x])


def _tail_log(n: int = 5) -> list[str]:
    try:
        lines = MARATHON_LOG.read_text(encoding="utf-8").splitlines()
        return lines[-n:]
    except OSError:
        return []


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    # A health endpoint must never 500 — wrap everything and report liveness.
    try:
        _reap()
        st = _read_status()
        applied = st["applied"] if st["applied"] is not None else _count_applied()
        target = st["target"] or int(os.environ.get("MARATHON_TARGET", "100"))
        session_expired = "SESSION EXPIRED" in st["note"].upper()
        return jsonify({
            "ok": True,
            "applied": applied,
            "target": target,
            "note": st["note"],
            "status_updated": st["updated"],
            "session_expired": session_expired,
            "marathon_pid": _proc.pid if _proc and _proc.poll() is None else None,
            "marathon_uptime_s": int(time.time() - _proc_started) if _proc else 0,
            "restarts": _restarts,
            "server_uptime_s": int(time.time() - START_TIME),
            "daily_cap": int(os.environ.get("DAILY_CAP", "25")),
            "log_tail": _tail_log(),
        })
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}), 200


@app.get("/diag")
def diag():
    """Diagnostic: is R2 configured, and what did the marathon log at startup?

    The marathon's detailed log (R2 restore result, search results, etc.) is
    written to a file, not Render's console, so this endpoint surfaces it.
    """
    try:
        env_present = {
            k: bool(os.environ.get(k, "").strip())
            for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                      "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "GEMINI_API_KEY")
        }
        log_head: list[str] = []
        try:
            lines = MARATHON_LOG.read_text(encoding="utf-8").splitlines()
            log_head = lines[:30]
        except OSError:
            pass
        # Surface any R2-related line from the whole log (restore/upload).
        r2_lines = []
        try:
            for ln in MARATHON_LOG.read_text(encoding="utf-8").splitlines():
                if "R2" in ln or "r2" in ln:
                    r2_lines.append(ln)
        except OSError:
            pass
        return jsonify({
            "env_present": env_present,
            "applied_file_count": _count_applied(),
            "marathon_log_head": log_head,
            "r2_lines": r2_lines[-15:],
        })
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}), 200


@app.get("/")
def index():
    try:
        _reap()
        st = _read_status()
        applied = st["applied"] if st["applied"] is not None else _count_applied()
        target = st["target"] or int(os.environ.get("MARATHON_TARGET", "100"))
        return (
            f"<h2>LinkedIn Marathon</h2>"
            f"<p>applied: <b>{applied}/{target}</b></p>"
            f"<p>note: {st['note'] or '-'}</p>"
            f"<p>updated: {st['updated'] or '-'}</p>"
            f"<p><a href='/health'>/health</a></p>"
        )
    except Exception as exc:  # noqa: BLE001
        return f"<h2>LinkedIn Marathon</h2><p>error: {exc}</p>", 200


def _shutdown(signum, frame):  # noqa: ARG001
    _log(f"received signal {signum}; stopping marathon")
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _proc.kill()
    sys.exit(0)


def main() -> int:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    _spawn_marathon()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
