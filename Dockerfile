# LinkedIn Marathon — Render deployment image.
#
# Why a Dockerfile instead of Render's "Python" runtime + build command?
#   The old build command was:
#       pip install -r requirements.txt && python -m patchright install --with-deps chromium
#   The `--with-deps` flag runs `apt-get` to install Chromium's system
#   libraries, and Render's free tier throttles/stalls that step (the build
#   hung for ~2 hours on it).
#
#   This image is based on the official Playwright image, which ALREADY has:
#     * a recent CPython
#     * Chromium v1234 (the exact build patchright 1.62.1 needs)
#     * every system library Chromium requires (libnss3, libatk, ...)
#     * PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
#   So the build only runs `pip install` — no apt-get, no browser download.
#
# patchright 1.62.1 is a fork of Playwright 1.62.x and uses the same browser
# registry + the same PLAYWRIGHT_BROWSERS_PATH, so it finds the pre-installed
# Chromium at /ms-playwright/chromium-1234 with no extra work.

FROM mcr.microsoft.com/playwright/python:v1.62.0

WORKDIR /app

# Install Python dependencies first (cached layer — only re-runs when
# requirements.txt changes).
COPY requirements.txt .
# The free-tier build network is flaky (pip "Could not fetch URL" /
# ReadTimeoutError). Retry the WHOLE install up to 3 times, each attempt with a
# long per-connection timeout and many per-URL retries. If all 3 attempts fail
# the build fails (correct); if any one succeeds the build continues.
RUN pip install --no-cache-dir --timeout 300 --retries 10 -r requirements.txt \
    || { echo "==> pip attempt 1 failed, retrying in 10s..."; sleep 10; \
         pip install --no-cache-dir --timeout 300 --retries 10 -r requirements.txt; } \
    || { echo "==> pip attempt 2 failed, retrying in 10s..."; sleep 10; \
         pip install --no-cache-dir --timeout 300 --retries 10 -r requirements.txt; }

# Tailscale: lets the container reach the user's Android phone (which runs a
# SOCKS5 proxy on its cellular connection) over a private tailnet. The phone's
# cellular IP is residential, so LinkedIn does not block it the way it blocks
# datacenter IPs. server.py starts tailscaled in userspace mode at boot when
# TAILSCALE_AUTH_KEY is set.
RUN (curl -fsSL https://tailscale.com/install.sh | sh) \
    || { echo "==> tailscale install attempt 1 failed, retrying in 10s..."; sleep 10; \
         curl -fsSL https://tailscale.com/install.sh | sh; }

# Copy the application (server.py + tools/).
COPY server.py .
COPY tools/ tools/

# Safety net: confirm the Chromium build patchright expects is present.
# The base image already has it, so this is a fast no-op. If (contrary to
# expectation) it is missing, download ONLY the browser binary — no apt-get,
# because the system libraries are already in the base image.
RUN if [ -d /ms-playwright/chromium-1234 ]; then \
        echo "==> Chromium v1234 already present in base image (no download)"; \
    else \
        echo "==> Chromium not found — downloading binary only (no system deps)"; \
        python -m patchright install chromium; \
    fi

# Render's Docker runtime does not preserve the base image's ENV vars at
# runtime, so re-declare the browser path explicitly. server.py also detects
# and forces this at startup (belt and suspenders).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Render sets PORT automatically; 10000 is the documented default.
EXPOSE 10000

CMD ["python", "server.py"]
