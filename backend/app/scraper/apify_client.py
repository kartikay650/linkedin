"""Fetch a creator's recent posts via an Apify no-cookie actor.

No burner account, no login, no proxy — Apify runs the actor on its own
infrastructure and eats the anti-bot risk. We call the actor synchronously
(run-sync-get-dataset-items returns the scraped items in the HTTP response) and
normalise them into the SAME dict shape the browser path produced, so nothing
downstream (dedup, relevance scoring, drafting, the dashboard) has to change.

Actor input/output schemas vary between actors, so:
  * input is built from settings.apify_input_json (a template with {url}/{limit}),
  * output is read defensively across the common field names.
Run `python -m app.scraper.check_apify --profile <url>` to see the raw output and
confirm the mapping before relying on it.
"""
import base64
import json
import time
from datetime import datetime

import httpx

from app.config import settings

API_ROOT = "https://api.apify.com/v2"


class ApifyError(Exception):
    pass


def _build_input(profile_url: str, limit: int) -> dict:
    raw = settings.apify_input_json.replace("{url}", profile_url).replace("{limit}", str(limit))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ApifyError(f"apify_input_json is not valid JSON after substitution: {e}: {raw!r}") from e


def _first(item: dict, *keys):
    for k in keys:
        v = item.get(k) if isinstance(item, dict) else None
        if v:
            return v
    return None


def _nested(item: dict, *path):
    cur = item
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _to_int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return v


def _tokens() -> list[str]:
    """All configured Apify account tokens, in failover order."""
    toks = [t.strip() for t in (settings.apify_tokens or "").split(",") if t.strip()]
    if not toks and settings.apify_token:
        toks = [settings.apify_token]
    return toks


def run_actor(actor_id: str, payload: dict) -> list[dict]:
    """Start an actor, poll to completion, return dataset items. Tries each Apify
    account in turn — if one is out of monthly credit (or errors), it falls over to
    the next, so multiple free accounts behave as one larger balance."""
    toks = _tokens()
    if not toks:
        raise ApifyError("no Apify token configured")
    actor = actor_id.replace("/", "~")
    last = None
    for tok in toks:
        try:
            return _run_with_token(actor, payload, tok)
        except ApifyError as e:
            last = e
    raise last or ApifyError("all Apify accounts failed")


def _run_with_token(actor: str, payload: dict, tok: str) -> list[dict]:
    token = {"token": tok}
    r = httpx.post(f"{API_ROOT}/acts/{actor}/runs", params=token, json=payload, timeout=60)
    if r.status_code >= 400:
        raise ApifyError(f"couldn't start actor ({r.status_code}): {r.text[:300]}")
    run = r.json()["data"]
    run_id = run["id"]
    deadline = settings.apify_timeout_seconds
    waited, interval = 0, 3
    status = run["status"]
    dataset_id = run.get("defaultDatasetId")
    while status not in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT") and waited < deadline:
        time.sleep(interval)
        waited += interval
        s = httpx.get(f"{API_ROOT}/actor-runs/{run_id}", params=token, timeout=30).json()["data"]
        status, dataset_id = s["status"], s.get("defaultDatasetId", dataset_id)
    if status != "SUCCEEDED":
        raise ApifyError(f"actor run did not succeed (status={status} after {waited}s)")
    if not dataset_id:
        raise ApifyError("actor run has no dataset id")
    items = httpx.get(f"{API_ROOT}/datasets/{dataset_id}/items", params={**token, "clean": "true"}, timeout=60).json()
    if not isinstance(items, list):
        raise ApifyError(f"expected a list of dataset items, got: {str(items)[:300]}")
    return items


def run_actor_raw(profile_url: str, limit: int) -> list[dict]:
    """Run the configured posts actor for one profile URL; return raw items."""
    return run_actor(settings.apify_actor_id, _build_input(profile_url, limit))


def start_actor(actor_id: str, payload: dict, webhook: dict | None = None) -> str:
    """Fire-and-forget: start an actor run and return its run id. Tries each account
    until one accepts the run (failover on exhausted credit)."""
    toks = _tokens()
    if not toks:
        raise ApifyError("no Apify token configured")
    actor = actor_id.replace("/", "~")
    last = None
    for tok in toks:
        params = {"token": tok}
        if webhook:
            params["webhooks"] = base64.b64encode(json.dumps([webhook]).encode()).decode()
        try:
            r = httpx.post(f"{API_ROOT}/acts/{actor}/runs", params=params, json=payload, timeout=60)
            if r.status_code >= 400:
                last = ApifyError(f"couldn't start actor ({r.status_code}): {r.text[:300]}")
                continue
            return r.json()["data"]["id"]
        except httpx.HTTPError as e:
            last = ApifyError(str(e))
    raise last or ApifyError("all Apify accounts failed to start the run")


def dataset_items(dataset_id: str) -> list[dict]:
    """Fetch a dataset's items. The dataset belongs to whichever account ran it, so
    we try each token until the owning one succeeds."""
    for tok in _tokens():
        r = httpx.get(f"{API_ROOT}/datasets/{dataset_id}/items", params={"token": tok, "clean": "true"}, timeout=60)
        if r.status_code < 400:
            items = r.json()
            return items if isinstance(items, list) else []
    return []


def account_usage() -> list[dict]:
    """Per-account monthly spend vs credit, for the expense tracker."""
    out = []
    for i, tok in enumerate(_tokens(), 1):
        entry = {"account": i, "used_usd": None, "limit_usd": None}
        try:
            usage = httpx.get(f"{API_ROOT}/users/me/usage/monthly", params={"token": tok}, timeout=15).json().get("data", {})
            entry["used_usd"] = round(float(usage.get("totalUsageCreditsUsdBeforeVolumeDiscount", 0)), 2)
            me = httpx.get(f"{API_ROOT}/users/me", params={"token": tok}, timeout=15).json().get("data", {})
            entry["limit_usd"] = me.get("plan", {}).get("monthlyUsageCreditsUsd")
        except Exception:
            pass
        out.append(entry)
    return out


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _normalise(item: dict) -> dict | None:
    """Map one raw actor item to our post shape, tolerating both flat schemas
    (supreme_coder-style) and nested ones (harvestapi-style). Returns None if it
    has no usable permalink (post_url is the dedup key)."""
    post_url = (
        _first(item, "linkedinUrl", "url", "postUrl", "post_url", "link", "shareLinkedinUrl", "shareUrl", "permalink")
        or _nested(item, "socialContent", "shareUrl")
    )
    if not post_url:
        return None

    text = _first(item, "text", "content", "commentary", "postText", "post_text", "description") or ""

    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    author_name = (
        _first(item, "authorName", "author_name", "authorFullName", "fullName")
        or _first(author, "name", "fullName", "full_name")
        or ""
    )
    author_url = (
        _first(item, "authorProfileUrl", "author_url", "authorUrl", "profileUrl")
        or _first(author, "linkedinUrl", "url", "profileUrl", "profile_url", "link")
        or ""
    )

    eng = item.get("engagement") if isinstance(item.get("engagement"), dict) else {}
    likes = _first(eng, "likes", "reactions") or _first(item, "likesCount", "numLikes", "reactionsCount", "totalReactionCount")
    comments = _first(eng, "comments") or _first(item, "commentsCount", "numComments")
    engagement = {}
    if likes is not None:
        engagement["likes"] = _to_int(likes)
    if comments is not None:
        engagement["comments"] = _to_int(comments)

    posted = _nested(item, "postedAt", "date") or _first(item, "postedAtISO", "postedAt", "publishedAt", "date")

    return {
        "author_name": author_name,
        "author_profile_url": author_url or "",
        "post_url": post_url,
        "content_snippet": (text or "")[:600],
        "posted_at": _parse_dt(posted),
        "engagement": engagement,
    }


def fetch_posts(profile_url: str, max_results: int = 5) -> list[dict]:
    """Run the configured Apify actor for one profile URL; return normalised posts.
    Retries on an empty result (see apify_retries_on_empty) since some actors
    intermittently return nothing for a profile that has posts."""
    attempts = 1 + max(0, settings.apify_retries_on_empty)
    items = []
    for _ in range(attempts):
        try:
            items = run_actor_raw(profile_url, max_results)
        except httpx.HTTPError as e:
            raise ApifyError(f"couldn't reach Apify: {e}") from e
        if items:
            break

    posts = [p for p in (_normalise(it) for it in items) if p]
    return posts[:max_results]
