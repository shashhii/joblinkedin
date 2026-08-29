# 24/7 Deployment — Render + Cloudflare (all free)

Runs the LinkedIn marathon continuously on a **free Render web service**, kept
awake by a **Cloudflare Worker cron** that pings it every 5 minutes. The
LinkedIn login + progress survive Render restarts via **Cloudflare R2**.

```
┌─────────────────┐   every 5 min    ┌──────────────────────────┐
│ Cloudflare      │ ──── /health ──▶ │ Render free web service  │
│ Worker (cron)   │ ◀─── JSON ────── │  server.py               │
│  + alerts       │                  │   └─ linkedin_marathon.py│
└─────────────────┘                  │        └─ Chromium (headless)
                                     └────────────┬─────────────┘
                                                  │ cookies + progress
                                                  ▼
                                     ┌──────────────────────────┐
                                     │ Cloudflare R2 (10 GB)    │
                                     │  session/cookies.json    │
                                     │  state/applied_jobs.txt  │
                                     └──────────────────────────┘
```

## What you need (all free)

| Service      | Free tier                          | Used for                          |
|--------------|------------------------------------|-----------------------------------|
| GitHub       | unlimited public repos             | source control (Render pulls it)  |
| Render       | 750 h/mo, 512 MB RAM, spins down   | runs the marathon 24/7            |
| Cloudflare   | Workers 100k req/day, R2 10 GB     | keep-alive cron + session storage |
| Gemini       | free API key                       | answers form questions, monitor   |

## Step 1 — Push the repo to GitHub

```bat
cd "c:\Users\shash\My Files\Projects\project"
git init
git add .
git commit -m "LinkedIn marathon: 24/7 Render + Cloudflare stack"
```

Create an **empty** repo on GitHub (e.g. `linkedin-marathon`, private is fine —
Render can pull private repos), then:

```bat
git remote add origin https://github.com/<you>/linkedin-marathon.git
git branch -M main
git push -u origin main
```

> `.gitignore` already excludes secrets (`.ai.env`) and runtime state.
> Double-check with `git status` that no `.env` / `.session/` files are staged.

## Step 2 — Create the R2 bucket + API token (Cloudflare)

1. Cloudflare dashboard → **Storage & Databases → R2 → Create bucket**
   (name e.g. `linkedin-marathon`, any location).
2. **R2 → Manage R2 API Tokens → Create API token**
   - Permission: **Admin** (or "Object Read & Write" on that bucket).
   - Copy the **Access Key ID** and **Secret Access Key**.
3. Your **Account ID** is in the Cloudflare dashboard URL
   (`dash.cloudflare.com/<ACCOUNT_ID>/`).

## Step 3 — Seed the LinkedIn session (one time, on your PC)

The marathon needs a logged-in LinkedIn session. Export it from your local
browser profile and push it to R2:

```bat
set R2_ACCOUNT_ID=<account id>
set R2_ACCESS_KEY_ID=<access key id>
set R2_SECRET_ACCESS_KEY=<secret>
set R2_BUCKET=linkedin-marathon
python tools\seed_session.py
```

Expected output: `SEED_OK: session + state uploaded to R2. Ready to deploy.`

> If it says "SESSION NOT LOGGED IN", log in once first:
> `python tools\linkedin_login.py` (or open the profile headed), then re-run.
>
> LinkedIn sessions last days–weeks. When the Worker alerts
> `session-expired`, just re-run this command.

## Step 4 — Create the Render service

1. Render dashboard → **New → Blueprint** → pick your GitHub repo.
   Render reads `render.yaml` and creates the service automatically.
   (Or **New → Web Service** and fill in manually — values are in
   `render.yaml`.)
2. In the service's **Environment** tab, add:

   | Variable             | Value                                  |
   |----------------------|----------------------------------------|
   | `GEMINI_API_KEY`     | your Gemini key                        |
   | `DAILY_CAP`          | `25`                                   |
   | `MARATHON_TARGET`    | `100`                                  |
   | `R2_ACCOUNT_ID`      | from Step 2                            |
   | `R2_ACCESS_KEY_ID`   | from Step 2                            |
   | `R2_SECRET_ACCESS_KEY` | from Step 2                          |
   | `R2_BUCKET`          | `linkedin-marathon`                    |

3. Deploy. First build takes ~5–10 min (it downloads Chromium).
4. Open `https://<your-app>.onrender.com/health` — you should see JSON with
   `ok: true` and the applied count.

## Step 5 — Deploy the Cloudflare Worker (keep-alive)

```bat
cd worker
npm install
```

Edit `wrangler.jsonc`:
- `vars.RENDER_URL` → your Render URL (e.g. `https://linkedin-marathon.onrender.com`)
- `vars.ALERT_WEBHOOK` → (optional) a Discord webhook URL for alerts

```bat
npx wrangler login
npx wrangler deploy
```

The cron (`*/5 * * * *`) now pings Render every 5 minutes, keeping it awake
and alerting you (Discord) only when something changes: service down, or
LinkedIn session expired.

Test manually: `https://<your-worker>.workers.dev/ping`

## Day-to-day

- **Watch progress:** `https://<your-app>.onrender.com/health`
  (or the Worker's `/ping`).
- **Session expired alert:** re-run `python tools\seed_session.py` locally
  (Step 3). The marathon picks the fresh session from R2 within ~30 min.
- **Change the daily cap / target:** edit the Render env vars; the service
  redeploys automatically.
- **Stop it:** delete the Render service (the Worker just stops alerting).

## Safety rails built in

- **Daily cap** (`DAILY_CAP=25`): hard stop per local day, rests until 00:05.
- **Pacing:** 15–35 s between applications, backoff on consecutive failures.
- **Single-instance lock:** the marathon can never run twice.
- **Session-expiry detection:** stops applying the moment LinkedIn shows the
  authwall (instead of burning the batch), waits for a fresh R2 session.
- **R2 sync:** cookies + progress uploaded after every batch, restored on
  every boot — a Render restart loses nothing.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Render build fails on `patchright install` | Check the build log; the `--with-deps` flag installs Chromium system libs. Retry the deploy. |
| `/health` says `marathon_pid: null` | Check Render logs; the supervisor restarts the marathon 30 s after a crash. |
| All jobs `FAILED:session-expired` | Re-run `seed_session.py` (Step 3). |
| Worker alert `down` repeatedly | Free Render can be slow to cold-start; the Worker waits 90 s. If it persists, check the Render service is actually deployed. |
| `R2 upload error` in marathon log | Verify the 4 `R2_*` env vars on Render. |
