# Deployment (live)

Serverless, burner-free, no Docker. Runs on Vercel + Supabase.

## Live URLs
- **Dashboard (frontend):** https://linkedin-dashboard-silk.vercel.app
- **API (backend):** https://linkedin-api-green.vercel.app
- **Repo:** https://github.com/kartikay650/linkedin (branch `main`)

## What's where
| Piece | Service | Notes |
|---|---|---|
| Frontend (Vite SPA) | Vercel project `linkedin-dashboard` | root dir `frontend/`, env `VITE_API_URL` → the API URL |
| API (FastAPI) | Vercel project `linkedin-api` | root dir `backend/`, ASGI via `backend/api/index.py` |
| Postgres + Storage | Supabase project `linkedin-engagement` | separate account/org from beetle; bucket `client-docs` |
| Post fetching | Apify (HarvestAPI actor), webhook-driven | `/apify/webhook` receives run-finished callbacks |

Deploys happen automatically on push to `main` (both projects are git-linked). Env
vars live in each Vercel project's Settings → Environment Variables (never in git).

## Running migrations (no Docker)
Schema changes go through Alembic against Supabase's **session pooler** (port 5432,
IPv4). From a machine with the backend deps installed:

```bash
cd backend
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
# session-pooler URL (5432), password from deploy/provision.env:
export DATABASE_URL="postgresql://postgres.<ref>:<db-pass>@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
python -m alembic upgrade head
```
The app itself uses the **transaction pooler** (port 6543) via the `DATABASE_URL`
env var on Vercel. Initial schema was created with `Base.metadata.create_all` +
`alembic stamp head` (the Alembic baseline is a no-op from the pre-Alembic era).

## Local secrets (gitignored)
- `deploy/deploy.env` — GitHub/Supabase/Vercel tokens
- `deploy/provision.env` — created project ref, DB password, service key, webhook secret

## ⚠ Open item: authentication
The dashboard and API are currently **public** (the old Caddy basic-auth went away
with Docker). Before real client data goes in, lock it down — Vercel Deployment
Protection (password, needs Pro) on both projects, or wire Supabase Auth into the
SPA + an auth check on the API. See the note in the handoff.
