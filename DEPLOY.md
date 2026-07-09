# Deploy: Supabase + Vercel (serverless, burner-free)

The app is now burner-free — the backend is a stateless HTTP service that calls
Apify + Anthropic + Postgres. No browser, no VM, no Docker required. Target stack:

- **Frontend (Vite SPA) → Vercel**
- **API (FastAPI) → Vercel serverless functions**
- **Postgres → Supabase**
- **Uploaded client docs → Supabase Storage** (serverless disk is ephemeral)
- **Apify → webhook-driven** (no polling; nothing stays open for minutes)

## Already done (in code, verified locally)

- Webhook mode: `POST /clients/{id}/sync` fires Apify runs and returns immediately;
  Apify calls `POST /apify/webhook?secret=...` when a run finishes, and that handler
  saves + scores the posts. Toggle with env: `APIFY_USE_WEBHOOKS=true` +
  `PUBLIC_BASE_URL` + `APIFY_WEBHOOK_SECRET`.
- Active import graph is browser-free; Redis removed.

## Remaining code changes before Vercel (need your accounts to test)

1. **Document uploads → Supabase Storage.** `upload_document` currently writes to a
   local `client_docs/` volume; Vercel has no persistent disk. Switch to a storage
   bucket (dual-mode: local disk when `SUPABASE_URL` unset, Supabase Storage when set).
2. **DB engine for serverless.** Use Supabase's **connection pooler** URL (port 6543,
   pgBouncer) as `DATABASE_URL`, and `poolclass=NullPool` in `db.py` so functions
   don't exhaust connections.
3. **Vercel entrypoint.** Add `api/index.py` exposing the ASGI `app` and a `vercel.json`
   routing all paths to it. Set function `maxDuration` to ~60s (extract/resolve is the
   longest sync call; sync itself is now instant via webhooks).
4. **Migrations out-of-band.** Don't run Alembic on startup in serverless. Run
   `alembic upgrade head` once against the Supabase URL from your machine/CI on deploy.

## Setup steps

### Supabase
1. Create a project. Copy the **pooler** connection string (Settings → Database →
   Connection pooling, "Transaction" mode, port 6543).
2. `DATABASE_URL=<pooler-url>` locally, then `alembic upgrade head` to create the schema.
3. Create a Storage bucket `client-docs` (private). Copy the project URL + service key.

### Vercel — API project
- Root = `backend/`. Env: `DATABASE_URL` (pooler), `ANTHROPIC_API_KEY`, `APIFY_TOKEN`,
  `APIFY_ACTOR_ID`, `APIFY_INPUT_JSON`, `APIFY_USE_WEBHOOKS=true`,
  `APIFY_WEBHOOK_SECRET` (a real secret, not the test one), `SUPABASE_URL`,
  `SUPABASE_SERVICE_KEY`, and `PUBLIC_BASE_URL` = this project's deployed URL.
- Deploy, note the URL, set `PUBLIC_BASE_URL` to it, redeploy.

### Vercel — frontend project
- Root = `frontend/`. Build `npm run build`, output `dist`. Env `VITE_API_URL` =
  the API project's URL (or a rewrite to it). Add Vercel password protection (or wire
  Supabase Auth) to replace the Caddy basic-auth.

### Verify end-to-end (only possible once deployed — Apify can't call localhost)
1. Add a client, upload a strategy doc (confirm it lands in Supabase Storage).
2. Extract brand profile; Track verified creators.
3. Hit **Sync now** → returns `{"status":"started"}` instantly. Within ~1-2 min,
   posts appear (Apify called `/apify/webhook`). Check the Apify console's webhook
   deliveries if not.

## Cost
Supabase free + Vercel free/hobby + Apify ~$5/mo + Anthropic usage ≈ **~$10/mo**, zero
servers to babysit.
