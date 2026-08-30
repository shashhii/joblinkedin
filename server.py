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


# ---------------------------------------------------------------------------
# Browser path fix (Render)
#
# The Docker image is based on mcr.microsoft.com/playwright/python, which
# ships Chromium at /ms-playwright and sets PLAYWRIGHT_BROWSERS_PATH to match.
# Render's Docker runtime does NOT preserve that image ENV var at runtime, so
# patchright falls back to the default ~/.cache/ms-playwright (empty) and
# every browser launch fails with "Executable doesn't exist" — which is why
# the marathon saw "0 jobs in list".
#
# Detect the real browser directory and force the env var here, BEFORE the
# marathon subprocess is spawned (it inherits this environment).
# ---------------------------------------------------------------------------
def _fix_browser_path() -> str:
    candidates = [
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip(),
        "/ms-playwright",
        str(Path.home() / ".cache" / "ms-playwright"),
        str(Path.home() / ".local" / "share" / "ms-playwright"),
    ]
    for cand in candidates:
        if not cand:
            continue
        p = Path(cand)
        if p.is_dir() and any(
            d.name.startswith(("chromium-1234", "chromium_headless_shell-1234"))
            for d in p.iterdir()
        ):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(p)
            return str(p)
    # Nothing found — keep whatever was there (the probe will report it).
    return os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "(none)")


BROWSER_PATH = _fix_browser_path()

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


@app.get("/probe")
def probe():
    """Open the LinkedIn search page (same way the marathon does) and report
    what LinkedIn actually shows: final URL, title, body text, card count.

    Used to diagnose '0 jobs in list' — distinguishes a genuine empty result
    from an authwall / CAPTCHA / 'unusual activity' block.
    """
    import json as _json
    import time as _time
    from pathlib import Path as _Path

    out = {"ok": False}
    try:
        from patchright.sync_api import sync_playwright

        # Browser-path diagnostics (the "0 jobs" root cause was the browser
        # not being found at the default path).
        out["browser_path_env"] = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "(unset)")
        out["browser_path_detected"] = BROWSER_PATH
        _bp = _Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
        out["browser_dir_contents"] = (
            sorted(p.name for p in _bp.iterdir()) if _bp.is_dir() else "(dir missing)"
        )

        profile = _Path.home() / ".linkedin-mcp" / "profile"
        url = (
            "https://www.linkedin.com/jobs/search/?"
            "keywords=software+engineer"
            "&location=Bengaluru"
            "&f_E=1%2C2%2C3"
            "&f_AL=true"
            "&f_TPR=r604800"
            "&sortBy=DD"
            "&start=0"
        )
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=True,
                no_viewport=True,
                args=[
                    "--start-maximized", "--no-sandbox",
                    "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--disable-extensions",
                    "--no-first-run", "--no-default-browser-check",
                ],
            )
            try:
                # Inject R2-restored cookies (same as linkedin_search.py).
                try:
                    import sys as _sys
                    _sys.path.insert(0, str(TOOLS))
                    import r2_sync
                    cookies = r2_sync.load_cookies()
                    if cookies:
                        ctx.add_cookies(cookies)
                        out["cookies_injected"] = len(cookies)
                    else:
                        out["cookies_injected"] = 0
                except Exception as exc:
                    out["cookie_inject_error"] = f"{exc.__class__.__name__}: {exc}"

                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                _time.sleep(5)
                # Scroll a bit like the real search does.
                for _ in range(3):
                    try:
                        page.mouse.wheel(0, 3000)
                    except Exception:
                        break
                    _time.sleep(1.0)

                out["final_url"] = page.url
                out["title"] = page.title()
                try:
                    body = page.inner_text("body")
                except Exception:
                    body = ""
                out["body_len"] = len(body)
                out["body_head"] = body[:1500]
                # Count job cards.
                try:
                    out["job_cards"] = page.locator(
                        "a[href*='/jobs/view/']").count()
                except Exception:
                    out["job_cards"] = -1
                # Authwall / block indicators.
                low = (page.url + " " + body).lower()
                out["looks_like_authwall"] = (
                    "authwall" in page.url or "/login" in page.url
                    or "sign in" in low or "log in" in low
                    or "unusual activity" in low
                    or "captcha" in low or "puzzle" in low
                    or "verify you are human" in low
                )
            finally:
                ctx.close()
        out["ok"] = True
        return jsonify(out)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{exc.__class__.__name__}: {exc}"
        return jsonify(out), 200


@app.get("/browser")
def browser_diag():
    """Filesystem diagnostic: where is the Chromium binary actually on Render?

    Lists candidate browser dirs, searches common roots for the executable,
    and reports the patchright version + driver location.
    """
    import shutil

    out: dict = {
        "home": str(Path.home()),
        "cwd": str(Path.cwd()),
        "env_browsers_path": os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "(unset)"),
        "detected": BROWSER_PATH,
        "dirs": {},
        "found_executables": [],
        "which_chromium": (
            shutil.which("chromium")
            or shutil.which("chromium-browser")
            or shutil.which("google-chrome")
            or "(none)"
        ),
    }

    candidates = [
        "/ms-playwright",
        str(Path.home() / ".cache" / "ms-playwright"),
        str(Path.home() / ".local" / "share" / "ms-playwright"),
        "/opt/render/.cache/ms-playwright",
        "/root/.cache/ms-playwright",
        "/app/.cache/ms-playwright",
    ]
    for cand in candidates:
        p = Path(cand)
        if p.is_dir():
            try:
                out["dirs"][cand] = sorted(x.name for x in p.iterdir())
            except OSError as exc:
                out["dirs"][cand] = f"(read error: {exc})"
        else:
            out["dirs"][cand] = "(missing)"

    # Search a few roots for the headless-shell / chromium executable.
    search_roots = ["/ms-playwright", str(Path.home()), "/opt/render", "/app", "/root"]
    for root in search_roots:
        rp = Path(root)
        if not rp.is_dir():
            continue
        try:
            for f in rp.rglob("*"):
                if f.is_file() and f.name in (
                    "chrome-headless-shell", "chrome", "headless_shell",
                ):
                    out["found_executables"].append(str(f))
                    if len(out["found_executables"]) >= 20:
                        break
        except OSError:
            continue
        if len(out["found_executables"]) >= 20:
            break

    # patchright version + driver location.
    try:
        import patchright
        out["patchright_version"] = getattr(patchright, "__version__", "(unknown)")
    except Exception as exc:  # noqa: BLE001
        out["patchright_version"] = f"(import error: {exc})"
    try:
        import patchright.driver as _drv
        out["driver_dir"] = str(Path(_drv.__file__).resolve().parent)
    except Exception as exc:  # noqa: BLE001
        out["driver_dir"] = f"(error: {exc})"

    return jsonify(out)


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
