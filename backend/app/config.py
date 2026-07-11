from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://linkedin:linkedin@postgres:5432/linkedin"

    # Serverless/webhook mode for Apify. When on (and public_base_url is set),
    # "Sync now" fires actor runs with a callback instead of polling, so no request
    # stays open for minutes — required for Vercel. Off = local polling.
    apify_use_webhooks: bool = False
    public_base_url: str = ""       # e.g. https://your-api.vercel.app — where Apify calls back
    apify_webhook_secret: str = ""  # shared secret; the /apify/webhook endpoint rejects mismatches

    # Serverless (Vercel): use NullPool so functions don't hold DB connections, and
    # store uploaded docs in Supabase Storage (Vercel's disk is ephemeral). When
    # supabase_url is unset, uploads fall back to local disk (client_docs_dir).
    serverless: bool = False
    supabase_url: str = ""              # e.g. https://<ref>.supabase.co
    supabase_service_key: str = ""      # service role key (server-side only, never shipped to browser)
    supabase_anon_key: str = ""         # public anon key — used to validate user JWTs against Supabase Auth
    supabase_docs_bucket: str = "client-docs"

    anthropic_api_key: str = ""
    relevance_model: str = "claude-haiku-4-5-20251001"
    draft_model: str = "claude-sonnet-5"

    # --- Post fetching provider -------------------------------------------
    # "apify"   → fetch creators' recent posts via an Apify no-cookie actor
    #             (no burner account, no login, no proxy — Apify eats the
    #             anti-bot risk). This is the intended production path.
    # "browser" → legacy Playwright-through-burner path (kept as a fallback).
    posts_provider: str = "browser"

    # Apify. Get the token from apify.com → Settings → Integrations → API token.
    apify_token: str = ""
    # Optional: multiple Apify account tokens, comma-separated. Calls fail over from
    # one to the next when an account runs out of monthly credit, so several free
    # accounts act as one larger balance. Falls back to apify_token if unset.
    apify_tokens: str = ""
    # Actor id in "username/actor-name" form (the / is auto-converted to ~ for the API).
    # Locked in: harvestapi's no-cookie profile-posts actor — cheapest ($1.50/1k)
    # and 100% run-success in vetting. Input: targetUrls[] + maxPosts.
    apify_actor_id: str = "harvestapi/linkedin-profile-posts"
    # Actor input as JSON with {url}/{limit} placeholders. We deliberately omit
    # reactions/comments detail (extra cost we don't need — we only use counts).
    apify_input_json: str = '{"targetUrls": ["{url}"], "maxPosts": {limit}}'
    # How long to wait for one actor run (they can take 30s–2min).
    apify_timeout_seconds: int = 120
    # Retry once if a run returns nothing. HarvestAPI is reliable so this rarely
    # fires; kept as cheap insurance (empty runs bill ~nothing).
    apify_retries_on_empty: int = 1
    # Actor used to resolve a person's name -> their LinkedIn profile URL (a Google
    # search over site:linkedin.com/in). Used during onboarding to auto-fill the
    # suggested watch-creators' links.
    apify_search_actor_id: str = "apify/google-search-scraper"

    # --- Residential proxy (PacketStream) ---------------------------------
    # PREFERRED: paste the exact proxy URL that PacketStream's dashboard
    # "Network Access" widget generates for you, but replace the sticky-session
    # portion with the literal placeholder {session}. Each burner substitutes
    # its own stable session id there, so every burner gets its OWN consistent
    # residential exit IP (real isolation) instead of one shared/rotating IP.
    #   e.g. http://myuser:myKey_country-US-session-{session}@proxy.packetstream.io:31112
    # The exact separators around country/session differ per provider account —
    # copy them verbatim from your dashboard rather than guessing. Confirm the
    # whole thing works with `python -m app.scraper.check_proxy` before any
    # LinkedIn traffic.
    proxy_url_template: str = ""

    # LEGACY fallback (no country/stickiness) — builds http://user:pass@host:port.
    packetstream_username: str = ""
    packetstream_password: str = ""
    packetstream_host: str = "proxy.packetstream.io"
    packetstream_port: int = 31112

    alert_webhook_url: str = ""  # Slack/Telegram incoming webhook

    client_docs_dir: str = "/app/client_docs"
    max_upload_size_mb: int = 15

    # Safety defaults — intentionally not exposed to the dashboard/ops UI.
    max_actions_per_burner_per_day: int = 20
    min_delay_seconds: int = 45
    max_delay_seconds: int = 180
    health_check_interval_minutes: int = 60

    class Config:
        env_file = ".env"


settings = Settings()
