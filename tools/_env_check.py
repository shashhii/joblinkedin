"""One-shot: report which env files exist and which keys are set (no secrets)."""
import pathlib

TOOLS = pathlib.Path(__file__).parent
for name in [".r2.env", ".linkedin.env", ".ai.env"]:
    p = TOOLS / name
    if not p.exists():
        print(f"{name}: MISSING")
        continue
    keys = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            keys.append(f"{k.strip()}={'SET' if v.strip() else 'EMPTY'}")
    print(f"{name}: {', '.join(keys) if keys else '(no keys)'}")

# Also check the session cookie file age
c = TOOLS / ".session" / "cookies.json"
if c.exists():
    import time
    age_h = (time.time() - c.stat().st_mtime) / 3600
    print(f"cookies.json: exists, {c.stat().st_size} bytes, {age_h:.1f}h old")
else:
    print("cookies.json: MISSING")
