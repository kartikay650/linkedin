"""Helpers for deciding whose posts belong in a client's feed.

A client should never see, in their OWN feed, posts written by themselves or by a
same-company colleague (e.g. Nikolina and Gordan are both at GlycanAge). Commenting
on your own company's post as if it were an outsider's reads wrong and is easy for a
human to miss, so we exclude those automatically.
"""
import re

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Client


def profile_slug(url: str) -> str:
    """The stable '/in/<slug>' handle from a LinkedIn profile URL, lowercased.
    Robust to query strings (?miniProfileUrn=...) and trailing slashes."""
    if not url:
        return ""
    m = re.search(r"/in/([^/?#]+)", url.lower())
    return m.group(1).strip() if m else ""


def excluded_author_slugs(db: Session, client: Client) -> set[str]:
    """Profile slugs whose posts must not appear in this client's feed: the client
    themselves, plus every other client sharing the same (non-empty) company."""
    slugs = set()
    own = profile_slug(client.linkedin_url or "")
    if own:
        slugs.add(own)
    company = (getattr(client, "company", "") or "").strip().lower()
    if company:
        colleagues = (
            db.query(Client)
            .filter(func.lower(func.trim(Client.company)) == company, Client.id != client.id)
            .all()
        )
        for c in colleagues:
            s = profile_slug(c.linkedin_url or "")
            if s:
                slugs.add(s)
    return slugs


def is_own_or_colleague_post(db: Session, client: Client, author_profile_url: str, source_ref: str = "") -> bool:
    """True if this post was authored by the client or a same-company colleague."""
    slug = profile_slug(author_profile_url) or profile_slug(source_ref)
    return bool(slug) and slug in excluded_author_slugs(db, client)
