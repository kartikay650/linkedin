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
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.llm.relevance import score_post
from app.models import Client, Creator, CreatorClient, Post, WatchCreator
from app.profiles import is_own_or_colleague_post
from app.scraper.apify_client import ApifyError, _build_input, fetch_posts as apify_fetch_posts, start_actor

# Recent posts to pull per source. Watch-creators (hand-picked, high-priority) get
# more; the shared creator database gets one recent post each so a sync surfaces the
# field without flooding the feed.
_WATCH_POSTS = 3
_GLOBAL_POSTS = 1

# Cadence: minimum days between re-fetching a profile, by how often they post. This
# is the spend control — infrequent posters aren't re-scraped on every sync. Tracked
# per PROFILE (Creator.last_fetched_at), so a profile shared by N clients is scraped
# once per its window and fanned out to all of them, never N times. Tune here.
_FETCH_CADENCE_DAYS = {"yes": 2, "sometimes": 7, "no": 30}
_DEFAULT_CADENCE_DAYS = 7
# Watch-creators are hand-picked/high-priority, so fetched more often than the shared
# list, but still capped so a same-day re-sync doesn't re-scrape them.
_WATCH_CADENCE_DAYS = 1

# Each /sync/fire request fires runs until this wall-clock budget, then returns the
# rest for the next request. Well under Vercel's 60s ceiling so a batch can never be
# killed mid-flight regardless of network latency (the real robustness lever).
_FIRE_BUDGET_SECONDS = 35.0
_FIRE_CALL_TIMEOUT = 10.0  # per start_actor POST — fail fast to failover, don't hang


def _creator_due(creator: Creator, now: datetime) -> bool:
    """Is this profile due for a re-fetch, given how often they post and when we last
    scraped them (globally, across all clients)?"""
    freq = (creator.post_frequency or "sometimes").lower()
    days = _FETCH_CADENCE_DAYS.get(freq, _DEFAULT_CADENCE_DAYS)
    last = creator.last_fetched_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= timedelta(days=days)


def _due_since(last, now, days) -> bool:
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last) >= timedelta(days=days)


def plan_profiles(db: Session, client: Client | None = None) -> list[dict]:
    """The de-duplicated work-list for a sync: unique profile URLs to fetch, each once.
    Universal (client=None) covers every client; client-scoped covers just that client.

    Sources = watch-creators (always fetched, high-priority) + tracked creators that
    are DUE by cadence AND assigned to at least one client (fetching an unassigned
    creator would waste credit — no feed to fan out to). Deduped by URL, so a profile
    tracked by several clients appears once."""
    now = datetime.now(timezone.utc)
    profiles: dict[str, dict] = {}

    def add(url, label, posts):
        url = (url or "").strip()
        if not url:
            return
        cur = profiles.get(url)
        if cur is None:
            profiles[url] = {"url": url, "label": label or "", "posts": posts}
        else:
            cur["posts"] = max(cur["posts"], posts)
            cur["label"] = cur["label"] or (label or "")

    watch = list(client.watch_creators) if client is not None else db.query(WatchCreator).all()
    for wc in watch:
        if _due_since(wc.last_fetched_at, now, _WATCH_CADENCE_DAYS):
            add(wc.profile_url, wc.label, _WATCH_POSTS)

    cq = (
        db.query(Creator)
        .join(CreatorClient, CreatorClient.creator_id == Creator.id)
        .filter(Creator.kind == "creator", Creator.active.is_(True))
    )
    if client is not None:
        cq = cq.filter(CreatorClient.client_id == client.id)
    for c in cq.distinct().all():
        if _creator_due(c, now):
            add(c.profile_url, c.name, _GLOBAL_POSTS)

    return list(profiles.values())


def fire_profiles(db: Session, profiles: list[dict], time_budget_s: float = _FIRE_BUDGET_SECONDS) -> tuple[int, list[dict]]:
    """Fire an Apify run per profile (fan-out webhook, so the posts land for EVERY
    client tracking that URL). Time-bounded: stops at the budget and returns the rest,
    so a single request never risks the 60s serverless kill. Stamps last_fetched_at on
    success so the next sync respects cadence. Returns (attempted_count, remaining)."""
    now = datetime.now(timezone.utc)
    start = time.monotonic()
    urls = [p["url"] for p in profiles]
    by_url = {}
    watch_by_url: dict[str, list] = {}
    if urls:
        for c in db.query(Creator).filter(Creator.profile_url.in_(urls)).all():
            by_url[c.profile_url] = c
        for wc in db.query(WatchCreator).filter(WatchCreator.profile_url.in_(urls)).all():
            watch_by_url.setdefault(wc.profile_url, []).append(wc)

    attempted = 0
    for i, p in enumerate(profiles):
        if time.monotonic() - start > time_budget_s:
            db.commit()
            return attempted, profiles[i:]
        url, label, posts = p["url"], p.get("label", ""), p.get("posts", _GLOBAL_POSTS)
        payload = _build_input(url, posts)
        webhook = _build_webhook(url, label)
        try:
            start_actor(settings.apify_actor_id, payload, webhook=webhook, timeout=_FIRE_CALL_TIMEOUT)
            # Stamp cadence on success only (creator AND any watch-creator with this URL);
            # failures stay due and retry next sync.
            c = by_url.get(url)
            if c is not None:
                c.last_fetched_at = now
            for wc in watch_by_url.get(url, []):
                wc.last_fetched_at = now
        except ApifyError as e:
            print(f"[sync] couldn't start run for {label or url}: {e}")
        attempted += 1
    db.commit()
    return attempted, []


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
    """Webhook mode, client-scoped (used by the daily cron / one-shot callers): fire this
    client's due profiles and return how many were attempted. The batched UI uses
    plan_profiles + fire_profiles directly. Posts arrive later via /apify/webhook."""
    attempted, _remaining = fire_profiles(db, plan_profiles(db, client))
    return attempted


def _build_webhook(source_ref: str, creator_label: str = "") -> dict:
    # Fan-out webhook: we bake only the profile URL (source_ref), NOT a client id — when
    # the run finishes, the handler saves the posts for EVERY client tracking this URL,
    # so a profile fetched once lands in all their feeds.
    # payloadTemplate is JSON-with-placeholders: our fields plus Apify's {{resource}}
    # (the finished run object, which carries defaultDatasetId).
    literal = json.dumps({"creator_label": creator_label, "source_ref": source_ref})
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
