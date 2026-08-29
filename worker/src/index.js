/**
 * linkedin-keepalive — Cloudflare Worker
 *
 * Every 5 minutes (cron) this worker:
 *   1. Pings the Render service's /health endpoint. The inbound HTTP request
 *      keeps the free Render instance awake (prevents the 15-min spin-down).
 *   2. Checks the JSON for problems (service down, session expired) and fires
 *      an alert to a webhook (Discord/Slack) only when the state CHANGES, so
 *      you don't get spammed.
 *
 * Config (wrangler.jsonc vars):
 *   RENDER_URL      https://your-app.onrender.com
 *   ALERT_WEBHOOK   (optional) Discord/Slack webhook URL for alerts
 *
 * Deploy:
 *   cd worker
 *   npm install
 *   npx wrangler deploy
 */

const STATE_TTL_SECONDS = 10 * 60; // remember last state for 10 min

export default {
  async scheduled(event, env, ctx) {
    await check(env, ctx);
  },

  // Manual trigger: GET https://<worker>/ping
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/ping") {
      const result = await check(env);
      return new Response(JSON.stringify(result, null, 2), {
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("linkedin-keepalive worker", { status: 200 });
  },
};

async function check(env, ctx) {
  const renderUrl = (env.RENDER_URL || "").replace(/\/$/, "");
  const result = {
    time: new Date().toISOString(),
    render_url: renderUrl,
    ok: false,
    detail: "",
    alert_sent: false,
  };

  if (!renderUrl) {
    result.detail = "RENDER_URL not configured";
    return result;
  }

  let health = null;
  try {
    const res = await fetch(renderUrl + "/health", {
      // Free Render cold-starts can take up to ~60s; give it room.
      signal: AbortSignal.timeout(90_000),
    });
    if (res.ok) {
      health = await res.json();
      result.ok = true;
      result.applied = health.applied;
      result.target = health.target;
      result.note = health.note;
      result.session_expired = health.session_expired;
    } else {
      result.detail = `HTTP ${res.status}`;
    }
  } catch (e) {
    result.detail = `fetch failed: ${e.message || e}`;
  }

  // Decide the current "problem state" (empty string = healthy).
  let problem = "";
  if (!result.ok) {
    problem = "down";
  } else if (health.session_expired) {
    problem = "session-expired";
  }

  // Alert only on state change (avoids spam every 5 min).
  const cache = await caches.open("keepalive-state");
  const prev = (await cache.match("state"))
    ? (await cache.match("state")).text()
    : null;
  if (problem && problem !== prev) {
    result.alert_sent = await sendAlert(env, problem, result);
  } else if (!problem && prev && prev !== "healthy") {
    result.alert_sent = await sendAlert(env, "recovered", result);
  }
  if (ctx && ctx.waitUntil) {
    ctx.waitUntil(
      cache.put(
        "state",
        new Response(problem || "healthy", {
          headers: { "cache-control": `max-age=${STATE_TTL_SECONDS}` },
        })
      )
    );
  }
  return result;
}

async function sendAlert(env, problem, result) {
  const webhook = env.ALERT_WEBHOOK;
  if (!webhook) return false;
  const lines = [
    `**LinkedIn marathon: ${problem}**`,
    `time: ${result.time}`,
    `render: ${result.render_url}`,
  ];
  if (result.applied != null) lines.push(`progress: ${result.applied}/${result.target}`);
  if (result.note) lines.push(`note: ${result.note}`);
  if (result.detail) lines.push(`detail: ${result.detail}`);
  if (problem === "session-expired") {
    lines.push(
      "Action: re-run `python tools/seed_session.py` locally to push a fresh login to R2."
    );
  }
  try {
    const body =
      webhook.includes("discord.com")
        ? { content: lines.join("\n") }
        : { text: lines.join("\n") };
    const res = await fetch(webhook, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    return res.ok;
  } catch {
    return false;
  }
}
