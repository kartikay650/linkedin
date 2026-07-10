"""Supabase Auth gate for the API. Every protected route depends on require_user,
which validates the caller's Supabase session JWT by asking Supabase who it belongs
to. Version-agnostic (works regardless of the project's JWT signing algorithm) at
the cost of one lightweight call to Supabase per request.

The Apify webhook is intentionally NOT behind this — it authenticates with its own
shared secret (it's called by Apify, not a logged-in user)."""
import httpx
from fastapi import Header, HTTPException

from app.config import settings


def require_user(authorization: str = Header(default="")):
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(500, "auth is not configured on the server")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "not signed in")

    token = authorization.split(" ", 1)[1].strip()
    try:
        r = httpx.get(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
            headers={"Authorization": f"Bearer {token}", "apikey": settings.supabase_anon_key},
            timeout=10,
        )
    except httpx.HTTPError:
        raise HTTPException(503, "couldn't verify session right now")

    if r.status_code != 200:
        raise HTTPException(401, "session invalid or expired — sign in again")
    return r.json()
