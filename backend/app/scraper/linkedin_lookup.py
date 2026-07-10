"""Resolve a person's name to their LinkedIn profile URL, and mark whether we're
confident it's the right person ("verified").

Uses a Google-search Apify actor over site:linkedin.com/in — no LinkedIn account
touched. "Verified" means the search result's title plausibly matches the name
(surname + at least one more name token present), which guards against picking a
same-named stranger. Even so, resolution only PRE-FILLS the URL in the onboarding
UI; a human still confirms before the creator is tracked.
"""
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.config import settings
from app.scraper.apify_client import run_actor, ApifyError

_LINKEDIN_IN = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[^/?#\s]+", re.I)


def _clean_name(name: str) -> str:
    # Drop credentials/suffixes ("Eric Verdin, MD" -> "Eric Verdin") for matching.
    return re.sub(r"[,|].*$", "", name).strip()


def _name_matches(name: str, text: str) -> bool:
    text_l = (text or "").lower()
    tokens = [t for t in re.split(r"\s+", _clean_name(name).lower()) if len(t) > 1]
    if not tokens:
        return False
    surname = tokens[-1]
    # Require the surname plus at least one other name token to appear.
    others = sum(1 for t in tokens[:-1] if t in text_l)
    return surname in text_l and (others >= 1 or len(tokens) == 1)


def _first_profile(items: list[dict], name: str) -> tuple[str, bool]:
    """Return (url, verified) for the best linkedin.com/in result, or ("", False)."""
    results = []
    for it in items:
        org = it.get("organicResults")
        if isinstance(org, list):
            results.extend(org)
        elif it.get("url"):
            results.append(it)

    fallback = ""
    for r in results:
        url = r.get("url") or ""
        m = _LINKEDIN_IN.search(url)
        if not m:
            continue
        clean_url = m.group(0)
        title = f"{r.get('title', '')} {r.get('description', '')}"
        if _name_matches(name, title):
            return clean_url, True
        if not fallback:
            fallback = clean_url
    # A /in/ URL was found but the title didn't clearly match — return unverified.
    return fallback, False


def resolve_creator_url(name: str, context: str = "") -> tuple[str, bool]:
    # Search by name + site filter only. We deliberately do NOT append the client's
    # specialty — a long, punctuation-heavy specialty string over-constrains the
    # Google query and returns zero results. The name-match check on the result
    # title (see _first_profile) is what guards against same-named strangers.
    query = f'"{_clean_name(name)}" site:linkedin.com/in'
    payload = {"queries": query, "maxPagesPerQuery": 1, "resultsPerPage": 10, "saveHtml": False}
    try:
        items = run_actor(settings.apify_search_actor_id, payload)
    except ApifyError:
        return "", False
    return _first_profile(items, name)


def resolve_creators(creators: list[dict], context: str = "") -> list[dict]:
    """Fill profile_url + verified for creators missing a URL. Runs lookups in
    parallel; best-effort (a failed lookup just leaves the URL blank)."""
    todo = [c for c in creators if not (c.get("profile_url") or "").strip()]
    if not todo:
        return creators

    results = {}
    with ThreadPoolExecutor(max_workers=min(6, len(todo))) as pool:
        futures = {pool.submit(resolve_creator_url, c["name"], context): id(c) for c in todo}
        for fut in as_completed(futures):
            try:
                results[futures[fut]] = fut.result()
            except Exception:
                results[futures[fut]] = ("", False)

    for c in creators:
        if id(c) in results:
            url, verified = results[id(c)]
            c["profile_url"] = url
            c["verified"] = verified
        else:
            c.setdefault("verified", bool((c.get("profile_url") or "").strip()))
    return creators
