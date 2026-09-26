"""One-command cloud session & credential initializer for Termux / new devices."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

def init_keys(r2_account: str = "", r2_access: str = "", r2_secret: str = "", r2_bucket: str = "linkedin-marathon", gemini_key: str = "") -> None:
    r2_file = HERE / ".r2.env"
    ai_file = HERE / ".ai.env"

    if r2_account and r2_access and r2_secret:
        r2_file.write_text(f"R2_ACCOUNT_ID={r2_account}\nR2_ACCESS_KEY_ID={r2_access}\nR2_SECRET_ACCESS_KEY={r2_secret}\nR2_BUCKET={r2_bucket}\n", encoding="utf-8")
        print(f"[*] Configured {r2_file.name}")

    if gemini_key:
        ai_file.write_text(f"GEMINI_API_KEY={gemini_key}\nGEMINI_MODEL=gemini-2.0-flash\n", encoding="utf-8")
        print(f"[*] Configured {ai_file.name}")

    # Clear any stale throttle/lock
    for f in [HERE / ".throttle_backoff.txt", HERE / ".marathon.lock", HERE / ".tried_jobs.txt", HERE / ".search_results.txt"]:
        if f.exists():
            try:
                f.unlink()
                print(f"[*] Cleared {f.name}")
            except OSError:
                pass

    # Test R2 cloud session pull
    try:
        sys.path.insert(0, str(HERE))
        import run_local
        run_local.load_env_file(".r2.env")
        import r2_sync
        ok = r2_sync.restore_session()
        if ok:
            cookies = r2_sync.load_cookies()
            print(f"[*] Cloud session restored from R2: SUCCESS ({len(cookies)} cookies synced)")
        else:
            print("[*] Cloud session restore from R2: Check credentials in tools/.r2.env")
    except Exception as exc:
        print(f"[*] R2 sync check: {exc}")


if __name__ == "__main__":
    init_keys()
