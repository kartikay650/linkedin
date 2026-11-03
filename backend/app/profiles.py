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


# LinkedIn's member ID, which survives a handle change. It rides on scraped author URLs as
# ?miniProfileUrn=urn%3Ali%3Afsd_profile%3A<ID> (encoded) or urn:li:fsd_profile:<ID>.
_MEMBER_ID_RE = re.compile(r"fsd_profile(?:%3A|:)([A-Za-z0-9_-]+)", re.I)
# The same pattern for Postgres `substring(... from ...)`, which returns the first capture group.
MEMBER_ID_SQL_PATTERN = r"fsd_profile(?:%3A|:)([A-Za-z0-9_-]+)"


def member_id(url: str) -> str:
    """LinkedIn member ID from a scraped profile URL, or "" if it carries none (~7% don't)."""
    m = _MEMBER_ID_RE.search(url or "")
    return m.group(1) if m else ""


def own_identities(db: Session, client: Client) -> tuple[set[str], set[str]]:
    """(handles, member IDs) whose posts must not appear in this client's feed: the client
    themselves plus every other client sharing the same (non-empty) company.

    Handles alone were not enough. Eric Verdin changed his from eric-verdin-490212 to
    eric-verdin-md, his posts kept arriving under the new one, and 17 of them sat in his own feed
    with drafts pending — one was the tool preparing to comment on his own post. The member ID is
    identical across both handles, so matching on either catches a rename; handles still cover the
    posts that carry no member ID."""
    people = [client]
    company = (getattr(client, "company", "") or "").strip().lower()
    if company:
        people += (
            db.query(Client)
            .filter(func.lower(func.trim(Client.company)) == company, Client.id != client.id)
            .all()
        )
    handles, ids = set(), set()
    for c in people:
        h = profile_slug(c.linkedin_url or "")
        if h:
            handles.add(h)
        mid = (getattr(c, "linkedin_member_id", "") or "").strip()
        if mid:
            ids.add(mid)
    return handles, ids


def is_own_or_colleague_post(db: Session, client: Client, author_profile_url: str, source_ref: str = "") -> bool:
    """True if this post was authored by the client or a same-company colleague, or was scraped
    from one of their own profiles.

    Author and source are checked independently. The old `author or source` only consulted the
    source when the author URL had no handle at all, so a post whose author handle was unknown
    but whose source was the client's own profile slipped through."""
    handles, ids = own_identities(db, client)
    if profile_slug(author_profile_url) in handles or profile_slug(source_ref) in handles:
        return True
    mid = member_id(author_profile_url)
    return bool(mid) and mid in ids


def remember_member_id(db: Session, client: Client, author_profile_url: str) -> None:
    """Record the client's member ID the first time one of their own posts arrives under their
    current handle, so a later handle change is still recognised. Only fires on the client's OWN
    handle (never a colleague's), and only when nothing is stored yet, so it cannot overwrite."""
    if (getattr(client, "linkedin_member_id", "") or "").strip():
        return
    if profile_slug(author_profile_url) != profile_slug(client.linkedin_url or ""):
        return
    mid = member_id(author_profile_url)
    if mid:
        client.linkedin_member_id = mid
        db.commit()
