#!/usr/bin/env bash
# ==============================================================================
# 24/7 Autonomous Job Application Engine (Termux & Linux Launcher)
# ==============================================================================

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=================================================="
echo " Starting 24/7 Career-Ops Autonomous Job Pipeline"
echo "=================================================="

# Ensure termux-wake-lock is held if on Android Termux
if command -v termux-wake-lock >/dev/null 2>&1; then
    echo "[*] Enabling Termux wake-lock..."
    termux-wake-lock
fi

# Find Python interpreter
if [ -n "$VIRTUAL_ENV" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
elif [ -f "$HOME/.local/bin/python" ]; then
    PYTHON="$HOME/.local/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    PYTHON="$(command -v python)"
fi

echo "[*] Using Python: $PYTHON"
echo "[*] Launching Watchdog Engine..."

exec "$PYTHON" "$DIR/tools/termux_engine.py" "$@"
