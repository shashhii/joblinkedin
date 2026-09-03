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
    from flask import request as _request

    out = {"ok": False}
    # A/B test: ?args=full makes /probe use the EXACT BROWSER_ARGS the search
    # uses (incl. the 192MB V8 heap cap). If probe-with-full-args returns 0
    # cards while default-args returns ~70, the memory flags are the culprit.
    use_full_args = _request.args.get("args") == "full"
    out["args_mode"] = "full" if use_full_args else "default"
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
            if use_full_args:
                import sys as _sys2
                _sys2.path.insert(0, str(TOOLS))
                import linkedin_search as _ls
                _args = list(_ls.BROWSER_ARGS)
            else:
                _args = [
                    "--start-maximized", "--no-sandbox",
                    "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                    "--disable-gpu", "--disable-extensions",
                    "--no-first-run", "--no-default-browser-check",
                ]
            _proxy = {}
            _purl = os.environ.get("PROXY_URL", "").strip()
            if _purl:
                # Preserve the scheme (http/https/socks5) so Webshare's
                # socks5:// endpoint works.
                if "://" in _purl:
                    _scheme, _rest = _purl.split("://", 1)
                else:
                    _scheme, _rest = "http", _purl
                _proxy = {"proxy": {"server": f"{_scheme}://{_rest}"}}
                if "@" in _rest:
                    _auth, _h = _rest.split("@", 1)
                    if ":" in _auth:
                        _u, _p = _auth.split(":", 1)
                        _proxy["proxy"]["username"] = _u
                        _proxy["proxy"]["password"] = _p
            out["proxy"] = "on" if _proxy else "off"
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=True,
                no_viewport=True,
                args=_args,
                **_proxy,
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
                # Count job cards (raw link count, same as before).
                try:
                    out["job_cards"] = page.locator(
                        "a[href*='/jobs/view/']").count()
                except Exception:
                    out["job_cards"] = -1
                # Also run the REAL extraction the search uses, so we can tell
                # whether 0-jobs is a rendering problem (raw>0, extracted=0)
                # or a selector problem (raw=0).
                try:
                    import sys as _sys3
                    _sys3.path.insert(0, str(TOOLS))
                    import linkedin_search as _ls2
                    _extracted = _ls2.extract_jobs(page)
                    out["extracted_jobs"] = len(_extracted)
                    if _extracted:
                        out["first_job"] = _extracted[0]
                except Exception as exc:
                    out["extracted_jobs"] = f"error: {exc.__class__.__name__}: {exc}"
                # DOM diagnostic: dump the HTML around the first job links so we
                # can see the REAL card-container structure (LinkedIn changed it,
                # which is why extract_jobs' selector matches 0 cards).
                if _request.args.get("dump") == "1":
                    try:
                        links = page.locator("a[href*='/jobs/view/']")
                        n = min(links.count(), 2)
                        out["dump_count"] = n
                        out["dump"] = []
                        for i in range(n):
                            a = links.nth(i)
                            # Walk up 3 ancestors and capture each outer HTML.
                            chain = []
                            node = a
                            for _ in range(3):
                                try:
                                    node = node.locator("xpath=..")
                                except Exception:
                                    break
                                try:
                                    chain.append(node.first.inner_html()[:1200])
                                except Exception:
                                    chain.append("(could not read)")
                            out["dump"].append(chain)
                    except Exception as exc:
                        out["dump_error"] = f"{exc.__class__.__name__}: {exc}"
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


def _start_tailscale() -> None:
    """Join the tailnet at boot (userspace mode — Render containers have no
    NET_ADMIN, so we cannot use a real TUN device).

    The phone's residential IP is used as a Tailscale EXIT NODE:
      * TAILSCALE_AUTH_KEY  — reusable key from the admin console; joins the
        tailnet on every boot (Render's filesystem is ephemeral).
      * TAILSCALE_EXIT_NODE — the phone's Tailscale IP. Once set, traffic that
        goes through the local SOCKS5 proxy (127.0.0.1:1053) exits via the
        phone's cellular connection. The browser is pointed at
        PROXY_URL=socks5://127.0.0.1:1053.

    In userspace mode only the browser's traffic (via 1053) is routed through
    the phone; R2 / Gemini / other traffic still goes direct, so a phone
    dropout does not take down the whole service.
    """
    auth_key = os.environ.get("TAILSCALE_AUTH_KEY", "").strip()
    if not auth_key:
        _log("tailscale: TAILSCALE_AUTH_KEY not set — skipping (no phone proxy)")
        return
    exit_node = os.environ.get("TAILSCALE_EXIT_NODE", "").strip()
    try:
        state_dir = "/var/lib/tailscale"
        os.makedirs(state_dir, exist_ok=True)
        log_path = f"{state_dir}/tailscaled.log"
        logf = open(log_path, "ab", buffering=0)
        proc = subprocess.Popen(
            [
                "tailscaled",
                "--tun=userspace-networking",
                f"--state={state_dir}/tailscaled.state",
                "--socks5-server=127.0.0.1:1053",
                "--outbound-http-proxy-listen=0",
            ],
            stdout=logf,
            stderr=logf,
            start_new_session=True,
        )
        _log(f"tailscale: tailscaled started (pid {proc.pid}), log -> {log_path}")
        # Wait up to 60s for the daemon to be reachable.
        daemon_up = False
        for _ in range(30):
            if proc.poll() is not None:
                _log(f"tailscale: tailscaled exited early (code {proc.returncode}) — see {log_path}")
                return
            try:
                st = subprocess.run(
                    ["tailscale", "status", "--json"],
                    capture_output=True, text=True, timeout=10,
                )
                if st.returncode == 0:
                    daemon_up = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not daemon_up:
            _log(f"tailscale: daemon not reachable after 60s — see {log_path}")
            return
        # Authenticate + join the tailnet (starting tailscaled alone does NOT join).
        up = subprocess.run(
            ["tailscale", "up", f"--auth-key={auth_key}"],
            capture_output=True, text=True, timeout=60,
        )
        if up.returncode != 0:
            _log(f"tailscale: 'tailscale up' failed: {up.stderr[:300]}")
            return
        _log("tailscale: joined tailnet, waiting for online...")
        # Wait up to 60s for the node to come online.
        online = False
        for _ in range(30):
            try:
                st = subprocess.run(
                    ["tailscale", "status", "--json"],
                    capture_output=True, text=True, timeout=10,
                )
                if st.returncode == 0 and '"Online":true' in st.stdout:
                    import json as _json
                    data = _json.loads(st.stdout)
                    self_ip = data.get("Self", {}).get("TailscaleIPs", ["?"])[0]
                    _log(f"tailscale: ONLINE, this node = {self_ip}")
                    online = True
                    break
            except Exception:
                pass
            time.sleep(2)
        if not online:
            _log("tailscale: still not online after 60s — will keep retrying in background")
            return
        # Route browser traffic (via the local SOCKS5 proxy) through the phone.
        if exit_node:
            for attempt in range(5):
                try:
                    es = subprocess.run(
                        ["tailscale", "set", f"--exit-node={exit_node}"],
                        capture_output=True, text=True, timeout=30,
                    )
                    if es.returncode == 0:
                        _log(f"tailscale: exit node set to {exit_node} (browser exits via phone)")
                        return
                    _log(f"tailscale: set exit node attempt {attempt + 1} failed: {es.stderr[:200]}")
                except Exception as exc:
                    _log(f"tailscale: set exit node error: {exc}")
                time.sleep(3)
            _log("tailscale: could not set exit node — browser will use direct connection")
    except Exception as exc:
        _log(f"tailscale: failed to start: {exc}")


@app.get("/ts")
def ts_diag():
    """Tailscale diagnostic: is the tailnet up, and can we reach the phone's
    SOCKS5 port?"""
    out: dict = {"tailscale_auth_key_set": bool(os.environ.get("TAILSCALE_AUTH_KEY", "").strip())}
    try:
        st = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if st.returncode == 0:
            import json as _json
            data = _json.loads(st.stdout)
            peers = []
            for ip, p in data.get("Peers", {}).items():
                peers.append({
                    "ip": ip,
                    "os": p.get("OS", ""),
                    "online": p.get("Online", False),
                    "name": (p.get("HostName") or "")[:40],
                })
            out["self_ip"] = (data.get("Self", {}).get("TailscaleIPs") or ["?"])[0]
            out["online"] = data.get("Self", {}).get("Online", False)
            out["peers"] = peers
        else:
            out["error"] = f"tailscale status failed: {st.stderr[:200]}"
    except Exception as exc:
        out["error"] = f"{exc.__class__.__name__}: {exc}"
    # Surface the tailscaled daemon log (last lines) for debugging.
    try:
        with open("/var/lib/tailscale/tailscaled.log", "rb") as lf:
            lf.seek(0, 2)
            size = lf.tell()
            lf.seek(max(0, size - 1500))
            out["daemon_log_tail"] = lf.read().decode("utf-8", "replace")[-1500:]
    except Exception:
        out["daemon_log_tail"] = "(no log file yet)"
    # If PROXY_URL points at a socks5:// tailnet IP, test TCP reachability.
    purl = os.environ.get("PROXY_URL", "").strip()
    if purl.startswith("socks5://"):
        try:
            hostport = purl.split("://", 1)[1].split("@")[-1]
            host, port = hostport.rsplit(":", 1)
            import socket as _sock
            s = _sock.create_connection((host, int(port)), timeout=10)
            s.close()
            out["phone_socks_reachable"] = True
        except Exception as exc:
            out["phone_socks_reachable"] = False
            out["phone_socks_error"] = f"{exc.__class__.__name__}: {exc}"
    return jsonify(out)


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
    _start_tailscale()
    _spawn_marathon()
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
