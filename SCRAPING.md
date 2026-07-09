# Sustainable LinkedIn scraping — setup & operating guide

This is the "do it right" version of the scraper: **burner accounts** (clients'
own accounts are never touched), each behind its **own sticky residential IP**
(PacketStream), with a **consistent per-burner fingerprint**, hosted cheaply on
**Oracle Cloud**. It's built to run ~10–15 clients with near-zero babysitting.

The honest framing: there is no permanently "undetectable" LinkedIn scraper —
it's an arms race, and automation against LinkedIn is against their ToS. What
this setup buys is *sustainability*: behave enough like a real person, from a
stable real-looking IP, at low volume, and sessions survive for weeks instead of
dying on the first action. The rest of this guide is how to keep it there.

---

## Why it kept dying before (root causes, now fixed in code)

1. **No proxy was actually on.** `proxy_url_template`/`PACKETSTREAM_*` were blank,
   so every request left from the server's raw IP. A fresh automated browser from
   a datacenter/home IP is about the most detectable combo possible.
2. **The one fetch path hit `/recent-activity/all/`** — a top automation tripwire.
   Now replaced: we read the creator's **base profile** activity preview instead
   (`scraper/creator_feed.py`).
3. **One burner scraped strangers for all clients**, with no per-burner IP or
   fingerprint isolation. Now each burner has its own sticky IP + locale/timezone.

## The proxy model (the big lever)

`scraper/proxy.py` is the single source of truth. Both the browser path
(Playwright) and the browserless path (httpx/Voyager) get their proxy from it,
so a burner's exit IP is identical no matter which runs. Resolution order:

1. `Burner.proxy_url` — explicit override for one burner.
2. `settings.proxy_url_template` with `{session}` → `Burner.proxy_session_id`
   (defaults to `burner<id>`). **This is the normal path.** Each burner gets a
   distinct, *stable* sticky session id → its own consistent residential IP.
3. Legacy `PACKETSTREAM_USERNAME/PASSWORD` — one shared IP, no stickiness.
4. None — direct (local dev only; `check_proxy` refuses to call this safe).

**Sticky matters:** a rotating IP is *worse* than a datacenter IP — LinkedIn
reads a session that hops IPs as account takeover. One burner = one IP, always.

---

## First-time setup

### 1. PacketStream
- Buy credit ($1/GB; scraping text is pennies).
- In the dashboard's **Network Access** widget, choose **country = US** (or match
  where the burner "lives"), **sticky session**, and copy the generated proxy
  string. Note the exact host/port and the exact separators around the country
  and session parameters — they vary per account.
- In `.env`, set `PROXY_URL_TEMPLATE` to that string, but replace the session
  value with the literal `{session}`. Example shape only:
  ```
  PROXY_URL_TEMPLATE=http://myuser:myKey_country-US-session-{session}@proxy.packetstream.io:31112
  ```
- `docker compose up -d backend` to reload env.

### 2. Verify the proxy BEFORE any LinkedIn traffic (zero risk)
```
docker compose exec backend python -m app.scraper.check_proxy --burner 1
```
Must show: exit IP ≠ your server IP, org = a home ISP (not a datacenter), and
**sticky** (two calls, one IP). Don't proceed until this passes.

### 3. Log the burner in — through the same proxy
Run locally (you need to see the window to solve 2FA/checkpoints):
```
python -m app.scraper.manual_login --burner 1
```
It launches through burner 1's proxy + fingerprint and writes the session to
that burner's `storage_state_path`. Logging in from your home IP and then
fetching from the proxy IP would checkpoint instantly — this keeps them identical.

### 4. First fetch
From the dashboard, add one watch-creator to a client and hit **Sync now**. Watch
`docker compose logs -f backend`. A healthy fetch loads the base profile, pauses
(human delay), and saves posts. If it checkpoints, see "If a burner dies" below.

---

## Making it browserless + cheapest (Voyager) — optional, recommended once stable

Running a headful browser per fetch is the heaviest part (CPU + proxy bandwidth
for full page renders). `scraper/voyager_api.py` talks to LinkedIn's internal
JSON API with just the burner's cookies — far less bandwidth, no browser needed
on the server. The endpoints are reverse-engineered and drift, so confirm which
one works against a live account first:
```
docker compose exec backend python -m app.scraper.verify_voyager --burner 1 \
    --profile https://www.linkedin.com/in/some-creator/
```
It prints which candidate endpoint returns real posts. Wire that endpoint into
`creator_feed.fetch_recent_posts` to drop the browser from the fetch path. (Login
still uses the browser, once, locally.)

---

## Deploying on Oracle Cloud (free ARM tier)

- Provision an **Always-Free Ampere A1** instance (up to 4 OCPU / 24 GB, $0/mo),
  Ubuntu 22.04, arm64. Install Docker + compose plugin.
- The backend image is `mcr.microsoft.com/playwright/python:v1.47.0-jammy`
  (multi-arch — runs on arm64) and already installs `xvfb`; `entrypoint.sh`
  starts `Xvfb :99` so headful Chromium works with no physical display.
- `git clone`, copy `.env` (with `PROXY_URL_TEMPLATE` set), `docker compose up -d`.
- Copy each burner's `sessions/burner_N.json` up **after** logging in locally,
  OR run `manual_login` via X-forwarding — but local login + scp is simpler.
- Re-run `check_proxy` on the VM to confirm the proxy resolves from there too.

Cost: Oracle $0 + PacketStream a few $/mo of bandwidth + Anthropic API usage.

---

## Scaling to 10–15 clients

- **Clients per burner, not one burner for everything.** Each burner has a hard
  cap of `MAX_ACTIONS_PER_BURNER_PER_DAY` (default 20) — see `config.py`. With a
  few watch-creators per client, plan roughly **3–5 clients per burner**, so
  10–15 clients ≈ **3–4 burners**, each with its own PacketStream sticky session
  (`proxy_session_id` differs per burner automatically) and ideally its own
  country/fingerprint if the burners are meant to look geographically distinct.
- Register each burner (DB row: `label`, `storage_state_path`, optionally
  `locale`/`timezone_id`), run `check_proxy`, then `manual_login`, per burner.
- **Warm up new burners:** a brand-new account with zero history scraping on day
  one is fragile. Log in, browse manually for a few days, keep daily actions low
  at first, then let discovery ramp.
- The scheduler (`jobs/scheduler.py`) runs discovery every 4h. For real load,
  consider dropping it to daily and relying on manual "Sync now" — fixed-interval
  automated bursts are the main way the daily cap gets hit silently.

---

## If a burner dies (checkpoint)

- The code flips it to `needs_relogin`, logs a `BurnerEvent`, alerts (if a webhook
  is set), and redistributes its clients to other active burners.
- **Do not hammer re-logins.** Repeated rapid relogin attempts are themselves a
  suspicious pattern. Give a checkpointed account 24–48h before re-logging in.
- Recover with `manual_login --burner N` (through its proxy). A `.bak` of the
  previous session is kept automatically (`session.py`) in case a refresh corrupts.
- If one account dies repeatedly regardless of method, it's burnt — retire it,
  spin up a fresh burner + a fresh sticky session.

## Hard limits to be honest about

- LinkedIn can server-side revoke a cookie anytime; no client-side trick prevents it.
- Voyager endpoints drift; treat `verify_voyager` output as ground truth, not the
  code comments.
- People-search / content-search (`feed_search.py`) remains the strongest tripwire
  and stays disabled — prospect discovery is stubbed until that's solved.
