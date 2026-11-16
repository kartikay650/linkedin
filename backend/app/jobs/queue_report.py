"""Why is a client's queue thin? A read-only count of where their posts went.

R27 (Umar, 10-11 Nov 2026): "very few comments for Nikolina" for 2-3 days, though all her
prospects are marked. A thin queue has several possible causes, and they need different fixes:
too few tracked profiles, profiles not fetched lately, posts hidden by the relevance bar, posts
lost to the two-feeds-per-post cap (and to whom), reposts, other languages. This counts each
one for the window the feed shows, so the cause is read off instead of guessed.

Run from backend/ with the production DATABASE_URL in the environment:
    python -m app.jobs.queue_report "Nikolina"            # last 14 days
    python -m app.jobs.queue_report "Noah" --days 7
It opens a READ ONLY transaction and only ever reads: no score, no fetch, no write.
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models import Client, Creator, CreatorClient, Post, WatchCreator, client_active
from app.profiles import profile_slug
from app.routers.posts import (MIN_DRAFT_RELEVANCE, PRIORITY_MIN_RELEVANCE, _HAS_WORK,
                               _visible_conditions)


def report(db: Session, client: Client, days: int = 14) -> dict:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=days)
    recent = now - timedelta(days=3)

    creators = (db.query(Creator).join(CreatorClient, CreatorClient.creator_id == Creator.id)
                .filter(CreatorClient.client_id == client.id).all())
    tracked = [c for c in creators if c.kind == "creator" and c.active]
    watch = db.query(WatchCreator).filter(WatchCreator.client_id == client.id).all()
    profiles = {
        "assigned_creators": len(tracked),
        # Assigned, but never fetched: kind='prospect' or switched off.
        "assigned_but_not_fetched": sorted(f"{c.name or c.profile_url} ({c.kind}"
                                           f"{'' if c.active else ', inactive'})"
                                           for c in creators if c not in tracked),
        "watch_creators": len(watch),
        "fetched_in_last_3_days": sum(1 for c in tracked if c.last_fetched_at and c.last_fetched_at >= recent)
        + sum(1 for w in watch if w.last_fetched_at and w.last_fetched_at >= recent),
        "never_fetched": sum(1 for c in tracked if c.last_fetched_at is None)
        + sum(1 for w in watch if w.last_fetched_at is None),
    }

    dt = func.coalesce(Post.posted_at, Post.fetched_at)
    rows = db.query(Post).filter(Post.client_id == client.id, dt >= cutoff).all()
    visible = {p.id for p in db.query(Post.id).filter(*_visible_conditions(db, client.id, days)).all()}
    with_work = {r[0] for r in db.query(Post.id).filter(Post.client_id == client.id, dt >= cutoff, _HAS_WORK).all()}

    reasons: Counter = Counter()
    lost_to: Counter = Counter()
    per_day: Counter = Counter()
    for p in rows:
        per_day[str((p.posted_at or p.fetched_at).date())] += 1
        if p.id in visible:
            reasons["in the feed"] += 1
            continue
        floor = PRIORITY_MIN_RELEVANCE if p.is_priority else MIN_DRAFT_RELEVANCE
        if p.dismissed:
            reasons["dismissed by a reviewer"] += 1
        elif (p.language or "en") != "en" and p.id not in with_work:
            reasons[f"not English ({p.language})"] += 1
        elif (p.relevance_score is not None and round(p.relevance_score * 10) < floor
              and p.id not in with_work):
            reasons["below the relevance bar"] += 1
        else:
            others = (db.query(Post.client_id, Client.name, Post.relevance_score, Post.is_priority)
                      .join(Client, Client.id == Post.client_id)
                      .filter(Post.post_url == p.post_url, Post.client_id != client.id,
                              Post.dismissed.is_(False), client_active(Post.client_id)).all())
            if len(others) >= 2:
                reasons["lost to the two-feeds-per-post cap"] += 1
                # The two that rank first: priority, then score (as _within_feed_quota orders them).
                ahead = sorted(others, key=lambda o: (bool(o[3]), o[2] if o[2] is not None else -1.0),
                               reverse=True)[:2]
                for _, name, score, prio in ahead:
                    lost_to[f"{name}{' (priority)' if prio else ''}"] += 1
            else:
                reasons["hidden for another reason (own or colleague post?)"] += 1

    elsewhere = sum(1 for p in rows if profile_slug(p.author_profile_url or "")
                    and profile_slug(p.source_ref or "")
                    and profile_slug(p.author_profile_url) != profile_slug(p.source_ref))
    return {
        "client": client.name,
        "window_days": days,
        "profiles": profiles,
        "posts_stored_in_window": len(rows),
        "unscored": sum(1 for p in rows if p.relevance_score is None),
        "author_differs_from_tracked_profile (reposts or handle changes)": elsewhere,
        "where_they_went": dict(reasons.most_common()),
        "cap_slots_taken_by": dict(lost_to.most_common()),
        "stored_per_day": dict(sorted(per_day.items())),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("client", help="part of the client's name, e.g. Nikolina")
    ap.add_argument("--days", type=int, default=14)
    args = ap.parse_args()
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        matches = db.query(Client).filter(Client.name.ilike(f"%{args.client}%")).all()
        if len(matches) != 1:
            raise SystemExit(f"{len(matches)} clients match {args.client!r}: "
                             + ", ".join(c.name for c in matches))
        print(json.dumps(report(db, matches[0], args.days), indent=2, default=str))
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    main()
