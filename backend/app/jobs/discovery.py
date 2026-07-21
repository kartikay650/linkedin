"""Post discovery via Apify. Two modes:

- Polling (local/dev, apify_use_webhooks=False): start each creator's actor run,
  wait for it, save posts synchronously. Fine on an always-on process; would time
  out on serverless.
- Webhook (deployed/serverless, apify_use_webhooks=True): fire each creator's run
  with a callback and return immediately. Apify calls /apify/webhook when the run
  finishes; that handler saves the posts. Nothing stays open for minutes.

The browser/burner path is gone — Apify is the only provider now.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.llm.relevance import score_post
from app.models import Client, Creator, CreatorClient, Post
from app.profiles import is_own_or_colleague_post
from app.scraper.apify_client import ApifyError, _build_input, fetch_posts as apify_fetch_posts, start_actor

# Recent posts to pull per source. Watch-creators (her hand-picked, high-priority
# profiles) get more; the shared creator database gets one recent post each so a
# sync surfaces the field without flooding the feed.
_WATCH_POSTS = 3
_GLOBAL_POSTS = 1
_GLOBAL_LIMIT = 200

# Cadence: minimum days between re-fetching a shared creator, by how often they post.
# This is the spend control — infrequent posters aren't re-scraped on every sync.
# "yes" posters are fetched often (fresh, catches new posts within the 5-day feed
# window); "sometimes"/"no" much less. Tune here to trade freshness vs cost.
_FETCH_CADENCE_DAYS = {"yes": 2, "sometimes": 7, "no": 30}
_DEFAULT_CADENCE_DAYS = 7


def _cadence_due(link: CreatorClient, now: datetime) -> bool:
    """Is this creator due for a re-fetch for this client, given its posting frequency?"""
    freq = (link.creator.post_frequency or "sometimes").lower()
    days = _FETCH_CADENCE_DAYS.get(freq, _DEFAULT_CADENCE_DAYS)
    last = link.last_fetched_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= timedelta(days=days)


def _active_creator_links(db: Session, client: Client):
    """CreatorClient links for tracked creators assigned to THIS client (creator eager-
    loaded), so the caller can read post_frequency / last_fetched_at for cadence."""
    return (
        db.query(CreatorClient)
        .join(Creator, Creator.id == CreatorClient.creator_id)
        .options(joinedload(CreatorClient.creator))
        .filter(
            CreatorClient.client_id == client.id,
            Creator.kind == "creator",
            Creator.active.is_(True),
        )
        .order_by(CreatorClient.creator_id)
        .limit(_GLOBAL_LIMIT)
        .all()
    )


def run_discovery_for_client(db: Session, client: Client) -> int:
    """Polling mode: fetch each watch-creator's posts now and save them.
    Returns the number of new posts. Used when apify_use_webhooks is off."""
    before = db.query(Post).filter(Post.client_id == client.id).count()
    for creator in client.watch_creators:
        try:
            posts = apify_fetch_posts(creator.profile_url, max_results=3)
        except ApifyError as e:
            print(f"[apify] {creator.label or creator.profile_url}: {e}")
            continue
        for raw in posts:
            raw["author_name"] = raw["author_name"] or creator.label
            _save_and_process(db, client, creator.profile_url, raw)
    after = db.query(Post).filter(Post.client_id == client.id).count()
    return after - before


def start_discovery_for_client(db: Session, client: Client) -> int:
    """Webhook mode: start one actor run per tracked profile with a callback, and
    return how many were started. Posts arrive later via /apify/webhook.

    Sources = this client's hand-picked watch-creators (always fetched) PLUS the
    shared creators assigned to this client that are DUE per their posting cadence
    (the spend control — infrequent posters are skipped until due)."""
    now = datetime.now(timezone.utc)
    # (url, label, max_posts, link) — dedupe by URL; watch-creators win and carry no
    # cadence link (they always fetch). `link` lets us stamp last_fetched_at after firing.
    sources = {}
    for c in client.watch_creators:
        sources[c.profile_url] = (c.label or "", _WATCH_POSTS, None)
    skipped_not_due = 0
    for link in _active_creator_links(db, client):
        g = link.creator
        if g.profile_url in sources:
            continue
        if not _cadence_due(link, now):
            skipped_not_due += 1
            continue
        sources[g.profile_url] = (g.name or "", _GLOBAL_POSTS, link)

    started = 0
    for url, (label, max_posts, link) in sources.items():
        payload = _build_input(url, max_posts)
        webhook = _build_webhook(client.id, label, url)
        try:
            start_actor(settings.apify_actor_id, payload, webhook=webhook)
            if link is not None:
                link.last_fetched_at = now  # only stamp shared creators; watch always refetch
            started += 1
        except ApifyError as e:
            print(f"[apify] couldn't start run for {label or url}: {e}")
    db.commit()  # persist cadence stamps so the next sync respects them
    if skipped_not_due:
        print(f"[sync] client {client.id}: fired {started}, skipped {skipped_not_due} not due for re-fetch")
    return started


def _build_webhook(client_id: int, creator_label: str, source_ref: str) -> dict:
    # payloadTemplate is JSON-with-placeholders: our own fields (baked in now) plus
    # Apify's {{resource}} (the finished run object, which carries defaultDatasetId).
    literal = json.dumps({"client_id": client_id, "creator_label": creator_label, "source_ref": source_ref})
    template = literal[:-1] + ', "resource": {{resource}}}'
    base = settings.public_base_url.rstrip("/")
    return {
        "eventTypes": ["ACTOR.RUN.SUCCEEDED"],
        "requestUrl": f"{base}/apify/webhook?secret={settings.apify_webhook_secret}",
        "payloadTemplate": template,
    }


def _save_and_process(db: Session, client: Client, source_ref: str, raw: dict) -> None:
    # Never surface a client's own posts, or a same-company colleague's, in their feed.
    if is_own_or_colleague_post(db, client, raw.get("author_profile_url", ""), source_ref):
        return
    post = Post(
        client_id=client.id,
        burner_id=None,  # burners retired; Apify has no per-account attribution
        source_type="creator",
        source_ref=source_ref,
        author_name=raw["author_name"],
        author_profile_url=raw["author_profile_url"],
        post_url=raw["post_url"],
        content_snippet=raw["content_snippet"],
        posted_at=raw.get("posted_at"),
        engagement=raw.get("engagement", {}),
    )
    db.add(post)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # already seen this post_url — dedup via the unique constraint
        return

    # Relevance is scored so the human can sort/filter; the reply text itself is
    # never generated until a person clicks "Draft reply". No auto-drafting here.
    score, reason, summary = score_post(client, post)
    post.relevance_score = score
    post.relevance_reason = reason
    post.summary = summary
    db.commit()
