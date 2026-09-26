"""Kill any lingering patchright/LinkedIn browsers (safe: only those using the
linkedin-mcp profile or patchright driver). Excludes itself and its shell."""
import json
import os
import subprocess

ME = os.getpid()
# Exclude ME and the immediate parent (the shell running us).
PARENTS = {ME}
try:
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-CimInstance Win32_Process -Filter 'ProcessId={ME}').ParentProcessId"],
        text=True, timeout=20).strip()
    if out.isdigit():
        PARENTS.add(int(out))
except Exception:
    pass

killed = 0
out = subprocess.check_output(
    ["powershell", "-NoProfile", "-Command",
     "Get-CimInstance Win32_Process | Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Depth 2"],
    text=True, timeout=30)
procs = json.loads(out)
if isinstance(procs, dict):
    procs = [procs]
for pr in procs:
    pid = pr.get("ProcessId")
    name = (pr.get("Name") or "").lower()
    cl = (pr.get("CommandLine") or "").lower()
    if pid in PARENTS or pid == ME:
        continue
    if name in ("chrome.exe", "chromium.exe", "headless_shell.exe", "python.exe", "node.exe"):
        if any(k in cl for k in ("linkedin-mcp", "patchright", "linkedin_search", "linkedin_marathon", "run_local")):
            print(f"killing {name} pid {pid}")
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=10)
                killed += 1
            except Exception as e:
                print(f"  failed: {e}")
print(f"total killed: {killed}")
