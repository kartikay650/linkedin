"""Direct-HTTP LinkedIn Voyager API client — same pattern as X-growth's
fetch-replies-x.py: authenticate with cookies captured once via browser login,
then talk to the internal API with plain httpx (no browser needed to fetch).

This is exploratory. LinkedIn does not publish these endpoints; the paths/params
below come from known reverse-engineered patterns (e.g. the tomquirk/linkedin-api
project) and may have drifted. Treat every call here as a hypothesis to verify
against a real response, not a guaranteed-working contract — log status codes
and raw bodies when a shape doesn't match instead of assuming.
"""
import json
import re
from pathlib import Path

import httpx

BASE = "https://www.linkedin.com/voyager/api"

DEFAULT_HEADERS = {
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "accept": "application/vnd.linkedin.normalized+json+2.1",
    "x-restli-protocol-version": "2.0.0",
    "x-li-lang": "en_US",
}


def _load_cookies(storage_state_path: str) -> dict:
    data = json.loads(Path(storage_state_path).read_text())
    cookies = {c["name"]: c["value"] for c in data["cookies"] if c["domain"].endswith("linkedin.com")}
    if "li_at" not in cookies or "JSESSIONID" not in cookies:
        raise RuntimeError("storage_state is missing li_at or JSESSIONID — session may be logged out")
    return cookies


def make_client(storage_state_path: str) -> httpx.Client:
    cookies = _load_cookies(storage_state_path)
    csrf = cookies["JSESSIONID"].strip('"')
    headers = {**DEFAULT_HEADERS, "csrf-token": csrf}
    return httpx.Client(headers=headers, cookies=cookies, timeout=20, follow_redirects=True)


def public_id_from_url(profile_url: str) -> str:
    m = re.search(r"/in/([^/?]+)", profile_url)
    if not m:
        raise ValueError(f"couldn't extract public id from {profile_url}")
    return m.group(1)


def get_profile_view(client: httpx.Client, public_id: str) -> dict:
    r = client.get(f"{BASE}/identity/profiles/{public_id}/profileView")
    return {"status": r.status_code, "url": str(r.url), "body": _safe_json(r)}


def try_profile_posts(client: httpx.Client, public_id: str, profile_urn: str | None, count: int = 10) -> list[dict]:
    """Try a few known candidate shapes for fetching a member's own posts.
    Returns a list of {label, status, url, body} — inspect these to see which
    one actually returns real post data before wiring anything into the pipeline."""
    attempts = []

    attempts.append(("posts_by_public_id", client.get(
        f"{BASE}/identity/profiles/{public_id}/posts",
        params={"count": count, "start": 0},
    )))

    if profile_urn:
        attempts.append(("feed_updates_member_share_feed", client.get(
            f"{BASE}/feed/updates",
            params={
                "q": "memberShareFeed",
                "moduleKey": "member-shares:phone",
                "profileUrn": profile_urn,
                "count": count,
                "start": 0,
            },
        )))

    out = []
    for label, r in attempts:
        out.append({"label": label, "status": r.status_code, "url": str(r.url), "body": _safe_json(r)})
    return out


def _safe_json(r: httpx.Response):
    try:
        return r.json()
    except Exception:
        return r.text[:500]
