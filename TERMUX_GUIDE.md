# 📱 Running the 24/7 Automation on Your Android Phone (Termux Guide)

This guide walks you through setting up and running the continuous job application engine on your Android phone using **Termux**.

---

## 🛠️ Step 1: Install Termux on Your Phone

1. **Download Termux**:
   * Download the latest APK from **F-Droid** or GitHub releases (⚠️ **Do NOT** use the Google Play Store version as it is deprecated):
   * [Download Termux on F-Droid](https://f-droid.org/en/packages/com.termux/)
2. Open Termux on your phone.

---

## 🚀 Step 2: One-Command Setup

Copy and paste this single command into Termux to install all dependencies and clone the project:

```bash
pkg update -y && pkg install -y git && git clone https://github.com/shashhii/joblinkedin.git ~/joblinkedin && cd ~/joblinkedin && chmod +x termux_setup.sh run_termux.sh && ./termux_setup.sh
```

---

## 🔑 Step 3: Cloud Session Sync (R2 & AI Setup)

The automation automatically pulls your active LinkedIn session cookies and application records directly from your Cloudflare R2 cloud storage.

Make sure your environment files are present in `tools/`:

```bash
cd ~/joblinkedin/tools
```

If you need to configure your R2 or AI keys:
```bash
# Create or edit .r2.env
nano .r2.env
# (Save with Ctrl+O, Enter, then exit with Ctrl+X)

# Create or edit .ai.env
nano .ai.env
```

---

## 🏃 Step 4: Start the 24/7 Automation Engine

Run the continuous self-healing engine:

```bash
cd ~/joblinkedin
./run_termux.sh
```

---

## 🔋 Step 5: Keep It Running 24/7 (Battery & Wake-Lock)

To ensure Android does not kill the process when your screen is off:

1. **Termux Wake-Lock**:
   * The script automatically acquires `termux-wake-lock`.
   * You will see a persistent notification from Termux in your notification shade: *"Termux wake lock acquired"*.
2. **Disable Android Battery Optimization**:
   * Go to your phone's **Settings -> Apps -> Termux -> Battery**.
   * Select **"Unrestricted"** (or disable *Battery Optimization* / *App Sleep*).
3. **Keep Phone on Wi-Fi / Charging**:
   * Keep your phone connected to your home Wi-Fi and plugged in or charged for uninterrupted 24/7 applications.

---

## 🔄 Self-Healing & Remote Updates from GitHub

* **Hotfixes from GitHub**: If you edit or push code to your GitHub repo, the background `git_updater` daemon in Termux will automatically detect the new commit, run `git pull`, install any new dependencies, and apply the update seamlessly without stopping the loop.
* **Health Status**: You can view real-time health stats at any time:
  ```bash
  cat ~/joblinkedin/tools/.marathon_status.txt
  cat ~/joblinkedin/tools/.applied_jobs.txt | wc -l
  ```
