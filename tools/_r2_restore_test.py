"""One-shot: load .r2.env and restore the LinkedIn session from R2."""
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Load R2 creds
p = HERE / ".r2.env"
for line in p.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import r2_sync

if not r2_sync.configured():
    print("R2 NOT CONFIGURED")
    sys.exit(1)

ok = r2_sync.restore_session()
print(f"restore_session -> {ok}")

# Report what we got
c = HERE / ".session" / "cookies.json"
if c.exists():
    import time, json
    age_h = (time.time() - c.stat().st_mtime) / 3600
    data = json.loads(c.read_text(encoding="utf-8"))
    print(f"cookies.json: {len(data)} cookies, {age_h:.1f}h old")
else:
    print("cookies.json: MISSING after restore")

a = HERE / ".applied_jobs.txt"
if a.exists():
    n = len([x for x in a.read_text(encoding="utf-8").splitlines() if x.strip()])
    print(f".applied_jobs.txt: {n} applied")
