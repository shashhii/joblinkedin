"""R2 session sync — persist the LinkedIn login + progress across Render boots.

Render's free tier has no persistent disk, so everything that must survive a
restart lives in Cloudflare R2 (S3-compatible, 10 GB free):

    session/cookies.json          LinkedIn cookies (Playwright format)
    state/applied_jobs.txt        submitted job ids
    state/tried_jobs.txt          attempted job ids
    state/daily_count.txt         "<day> <count>" daily-cap counter
    state/autopilot_results.txt   per-job results history

Credentials come from environment variables (set in Render's dashboard):
    R2_ACCOUNT_ID       Cloudflare account id
    R2_ACCESS_KEY_ID    R2 API token access key id
    R2_SECRET_ACCESS_KEY R2 API token secret
    R2_BUCKET           bucket name (e.g. "linkedin-marathon")

Local runs without these vars are a no-op (the module degrades gracefully).

CLI:
    python tools/r2_sync.py --status     show config + remote object listing
    python tools/r2_sync.py --upload     push local session + state to R2
    python tools/r2_sync.py --restore    pull R2 session + state to local
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SESSION_DIR = HERE / ".session"
COOKIES_FILE = SESSION_DIR / "cookies.json"

# State files that must survive a Render restart (relative to tools/).
STATE_FILES = [
    ".applied_jobs.txt",
    ".tried_jobs.txt",
    ".daily_count.txt",
    ".autopilot_results.txt",
]

R2_PREFIX = "linkedin-marathon"


def log(msg: str) -> None:
    print(f"[r2] {msg}", flush=True)


def _env() -> dict[str, str]:
    return {
        "account_id": os.environ.get("R2_ACCOUNT_ID", "").strip(),
        "access_key_id": os.environ.get("R2_ACCESS_KEY_ID", "").strip(),
        "secret_access_key": os.environ.get("R2_SECRET_ACCESS_KEY", "").strip(),
        "bucket": os.environ.get("R2_BUCKET", "").strip(),
    }


def configured() -> bool:
    e = _env()
    return all([e["account_id"], e["access_key_id"], e["secret_access_key"], e["bucket"]])


def _client():
    """Build a boto3 S3 client pointed at R2. Raises if not configured."""
    if not configured():
        raise RuntimeError("R2 not configured (missing R2_* env vars)")
    import boto3
    from botocore.client import Config

    e = _env()
    endpoint = f"https://{e['account_id']}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=e["access_key_id"],
        aws_secret_access_key=e["secret_access_key"],
        config=Config(s3={"addressing_style": "virtual"}),
    )


def _bucket() -> str:
    return _env()["bucket"]


# ---------------------------------------------------------------------------
# Local cookie file (used by linkedin_apply.py / linkedin_search.py)
# ---------------------------------------------------------------------------

def load_cookies() -> list[dict]:
    """Read LinkedIn cookies from tools/.session/cookies.json ([] if absent)."""
    try:
        data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return []


def save_cookies(cookies: list[dict]) -> None:
    """Write Playwright cookies to tools/.session/cookies.json."""
    try:
        SESSION_DIR.mkdir(exist_ok=True)
        COOKIES_FILE.write_text(json.dumps(cookies, indent=1), encoding="utf-8")
    except OSError as exc:
        log(f"cookie save failed: {exc}")


def export_cookies_from_context(context) -> int:
    """Pull cookies out of a live browser context and save them locally."""
    try:
        cookies = context.cookies()
        save_cookies(cookies)
        return len(cookies)
    except Exception as exc:
        log(f"cookie export failed: {exc.__class__.__name__}")
        return 0


# ---------------------------------------------------------------------------
# R2 upload / restore
# ---------------------------------------------------------------------------

def _put_text(key: str, text: str) -> None:
    _client().put_object(Bucket=_bucket(), Key=f"{R2_PREFIX}/{key}",
                         Body=text.encode("utf-8"))


def _get_text(key: str) -> str | None:
    try:
        obj = _client().get_object(Bucket=_bucket(), Key=f"{R2_PREFIX}/{key}")
        return obj["Body"].read().decode("utf-8")
    except Exception:
        return None


def upload_session() -> bool:
    """Push local cookies + state files to R2. True on success."""
    if not configured():
        return False
    uploaded = 0
    if COOKIES_FILE.exists():
        _put_text("session/cookies.json", COOKIES_FILE.read_text(encoding="utf-8"))
        uploaded += 1
    for name in STATE_FILES:
        p = HERE / name
        if p.exists():
            _put_text(f"state/{name.lstrip('.')}", p.read_text(encoding="utf-8"))
            uploaded += 1
    log(f"uploaded {uploaded} objects to R2")
    return uploaded > 0


def restore_session() -> bool:
    """Pull cookies + state files from R2 into local files. True on success."""
    if not configured():
        return False
    restored = 0
    cookies_text = _get_text("session/cookies.json")
    if cookies_text:
        try:
            data = json.loads(cookies_text)
            if isinstance(data, list) and data:
                SESSION_DIR.mkdir(exist_ok=True)
                COOKIES_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
                restored += 1
        except ValueError:
            log("remote cookies.json was not valid JSON; skipped")
    for name in STATE_FILES:
        text = _get_text(f"state/{name.lstrip('.')}")
        if text is not None:
            try:
                (HERE / name).write_text(text, encoding="utf-8")
                restored += 1
            except OSError:
                pass
    log(f"restored {restored} objects from R2")
    return restored > 0


def list_remote() -> list[str]:
    """List object keys currently in the R2 bucket (for --status)."""
    if not configured():
        return []
    try:
        resp = _client().list_objects_v2(Bucket=_bucket(), Prefix=f"{R2_PREFIX}/")
        return [o["Key"] for o in resp.get("Contents", [])]
    except Exception as exc:
        log(f"list failed: {exc.__class__.__name__}")
        return []


def main() -> int:
    args = sys.argv[1:]
    if "--status" in args:
        if not configured():
            print("R2 not configured (set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                  "R2_SECRET_ACCESS_KEY, R2_BUCKET)")
            return 1
        print(f"bucket: {_bucket()}")
        keys = list_remote()
        if not keys:
            print("(no objects yet)")
        for k in keys:
            print(f"  {k}")
        return 0
    if "--upload" in args:
        ok = upload_session()
        print("UPLOAD_OK" if ok else "UPLOAD_FAILED")
        return 0 if ok else 1
    if "--restore" in args:
        ok = restore_session()
        print("RESTORE_OK" if ok else "RESTORE_FAILED")
        return 0 if ok else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
