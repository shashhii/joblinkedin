#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
# One-Command Automated Termux Setup for Career-Ops 24/7 Automation
# ==============================================================================

set -e

echo "=================================================="
echo " Setting up Career-Ops Automation on Termux"
echo "=================================================="

# 1. Update Termux base packages
echo "[1/4] Updating Termux packages..."
pkg update -y

# 2. Install Git, Python, pre-compiled C-libraries, and build tools
echo "[2/4] Installing Git, Python, and system dependencies..."
pkg install -y git python python-pip nodejs clang make libffi libxml2 libxslt libjpeg-turbo freetype python-cryptography python-pillow

# 3. Install Python libraries using --break-system-packages (standard for Termux)
echo "[3/4] Installing Python libraries (ReportLab, Boto3, Requests, Dotenv, Patchright)..."
pip install --break-system-packages reportlab requests python-dotenv boto3 patchright

# 4. Make execution scripts executable & initialize cloud sync
echo "[4/4] Initializing Cloudflare R2 session & AI credentials..."
chmod +x run_termux.sh termux_setup.sh
python tools/setup_keys.py

# 5. Acquire Termux wake-lock
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
    echo "[*] Termux wake-lock enabled (CPU will stay active in background)."
fi

echo "=================================================="
echo " Setup Complete!"
echo " To start the 24/7 automation, run:"
echo "   ./run_termux.sh"
echo "=================================================="
