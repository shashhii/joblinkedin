"""Run the LinkedIn marathon on THIS computer (no Render, no proxy).

Your home connection has a residential IP, which is exactly what LinkedIn
wants to see. This script:
  1. Loads R2 credentials from tools/.r2.env (so the freshest LinkedIn
     session + applied-list are restored from the cloud).
  2. Makes sure PROXY_URL is NOT set (direct connection).
  3. Launches linkedin_marathon.py in the foreground.

Usage:
    python tools/run_local.py            # target 100, headless
    python tools/run_local.py --headed   # watch the browser work
    python tools/run_local.py --target 20
"""
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def load_env_file(name: str) -> None:
    """Load KEY=VALUE pairs from tools/<name> into os.environ (no overwrite)."""
    p = HERE / name
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def main() -> int:
    # R2 credentials (session + applied-list restore).
    load_env_file(".r2.env")
    # AI monitor (optional, degrades gracefully).
    load_env_file(".ai.env")

    # Direct connection — no proxy of any kind.
    os.environ.pop("PROXY_URL", None)

    if not all(os.environ.get(k) for k in
               ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY", "R2_BUCKET")):
        print("WARNING: R2 credentials missing — will use local session only.")

    cmd = [sys.executable, str(HERE / "linkedin_marathon.py")]
    for arg in sys.argv[1:]:
        cmd.append(arg)

    print(f"Launching: {' '.join(cmd)}")
    print("Your PC must stay ON and awake (disable sleep) for it to run 24/7.")
    return subprocess.call(cmd, cwd=str(HERE.parent))


if __name__ == "__main__":
    raise SystemExit(main())
