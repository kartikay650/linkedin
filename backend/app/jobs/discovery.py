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
import re
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.llm.relevance import score_post
from app.models import Client, Creator, CreatorClient, Post, WatchCreator, client_active
from app.lang import detect_language
from app.profiles import is_own_or_colleague_post, profile_slug, remember_member_id
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
_FETCH_CADENCE_DAYS = {"yes": 2, "sometimes": 3, "no": 30}
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


def plan_profiles(db: Session, client: Client | None = None, force: bool = False) -> list[dict]:
    """The de-duplicated work-list for a sync: unique profile URLs to fetch, each once.
    Universal (client=None) covers every client; client-scoped covers just that client.

    Sources = watch-creators (always fetched, high-priority) + tracked creators that
    are DUE by cadence AND assigned to at least one client (fetching an unassigned
    creator would waste credit — no feed to fan out to). Deduped by URL, so a profile
    tracked by several clients appears once.

    force=True ignores the cadence gate and includes EVERY assigned profile — the
    on-demand 'fetch latest now' for when someone knows a creator just posted and the
    normal (cadence-respecting) sync said nothing was due. Costs more, so it's explicit.

    Archived clients are left out everywhere: a profile tracked only by archived clients is not
    fetched, and syncing an archived client fetches nothing."""
    if client is not None and client.archived:
        return []
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

    watch = (list(client.watch_creators) if client is not None
             else db.query(WatchCreator).filter(client_active(WatchCreator.client_id)).all())
    for wc in watch:
        if force or _due_since(wc.last_fetched_at, now, _WATCH_CADENCE_DAYS):
            add(wc.profile_url, wc.label, _WATCH_POSTS)

    cq = (
        db.query(Creator)
        .join(CreatorClient, CreatorClient.creator_id == Creator.id)
        .filter(Creator.kind == "creator", Creator.active.is_(True))
    )
    if client is not None:
        cq = cq.filter(CreatorClient.client_id == client.id)
    else:
        cq = cq.filter(client_active(CreatorClient.client_id))
    for c in cq.distinct().all():
        if force or _creator_due(c, now):
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


def backfill_client_creator(db: Session, client: Client, source_ref: str, max_age_days: int = 14) -> int:
    """Give `client` the recent posts we ALREADY have for this profile URL (scraped for
    other clients), so a newly-assigned client isn't empty and we don't re-scrape. No
    Apify cost — reuses stored posts; scores relevance for this client. Returns # added.
    An archived client gets nothing (each post would be a paid relevance call)."""
    if client.archived:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    have = {
        r[0] for r in db.query(Post.post_url)
        .filter(Post.client_id == client.id, Post.source_ref == source_ref).all()
    }
    srcs: dict[str, Post] = {}
    for p in db.query(Post).filter(Post.source_ref == source_ref).order_by(Post.fetched_at.desc()).all():
        if p.client_id == client.id or p.post_url in have or p.post_url in srcs:
            continue
        dt = p.posted_at or p.fetched_at
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue
        srcs[p.post_url] = p
    added = 0
    for p in srcs.values():
        raw = {
            "author_name": p.author_name, "author_profile_url": p.author_profile_url,
            "post_url": p.post_url, "content_snippet": p.content_snippet,
            "posted_at": p.posted_at, "engagement": p.engagement or {},
        }
        _save_and_process(db, client, source_ref, raw)
        added += 1
    return added


def backfill_client(db: Session, client: Client, time_budget_s: float = 40.0) -> tuple[int, int]:
    """Backfill a client from stored posts for every profile assigned to them (creators
    + watch). Time-bounded for serverless; returns (posts_added, profiles_processed)."""
    start = time.monotonic()
    urls = [
        r[0] for r in db.query(Creator.profile_url)
        .join(CreatorClient, CreatorClient.creator_id == Creator.id)
        .filter(CreatorClient.client_id == client.id).all()
    ]
    urls += [r[0] for r in db.query(WatchCreator.profile_url).filter(WatchCreator.client_id == client.id).all()]
    added = processed = 0
    for url in dict.fromkeys(urls):  # dedupe, preserve order
        if time.monotonic() - start > time_budget_s:
            break
        added += backfill_client_creator(db, client, url)
        processed += 1
    return added, processed


def run_discovery_for_client(db: Session, client: Client) -> int:
    """Polling mode: fetch each watch-creator's posts now and save them.
    Returns the number of new posts. Used when apify_use_webhooks is off."""
    if client.archived:
        return 0
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


def _is_priority_creator(db: Session, client_id: int, source_ref: str) -> bool:
    """Has this client been given first claim on this creator? Read once per saved post, in a
    background job, so a small query here is fine — and it keeps the feed read cheap."""
    slug = profile_slug(source_ref)
    if not slug:
        return False
    row = (
        db.query(CreatorClient.id)
        .join(Creator, Creator.id == CreatorClient.creator_id)
        .filter(CreatorClient.client_id == client_id, CreatorClient.priority.is_(True))
        .filter(func.lower(Creator.profile_url).contains(f"/in/{slug}"))
        .first()
    )
    return row is not None


# Words in a name that say nothing about who someone is.
_NAME_NOISE = frozenset("dr prof professor mr mrs ms md phd mba msc bsc rn do frcp facp jr sr".split())


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.findall(r"[a-z\u00c0-\u024f]+", (name or "").lower())
            if len(t) > 1 and t not in _NAME_NOISE]


def _same_person(a: str, b: str) -> bool:
    """Do two display names plausibly belong to one person? Surname-led: the last real word of
    either name appears in the other ("Eric Verdin" / "Dr. Eric Verdin, MD")."""
    ta, tb = _name_tokens(a), _name_tokens(b)
    if not ta or not tb:
        return False
    return ta[-1] in tb or tb[-1] in ta


def _tracked_names(db: Session, source_ref: str) -> list[str]:
    """The names we hold for the profile a post was fetched from: the shared creator row and any
    hand-picked watch-creator label."""
    names = [r[0] for r in db.query(Creator.name).filter(Creator.profile_url == source_ref).all()]
    names += [r[0] for r in db.query(WatchCreator.label).filter(WatchCreator.profile_url == source_ref).all()]
    return [n for n in names if n and n.strip()]


def is_someone_elses_post(db: Session, source_ref: str, raw: dict) -> bool:
    """True when a post fetched from a tracked profile was written by somebody else: a repost.

    Nobody chose that author for the client, and the post is about whatever they wrote, which is
    how Noah's feed showed posts "completely different from his profile" (Baba, 10 Nov). The actor
    is asked for no reposts (apify_client._build_input) and flags the ones it can see; this is the
    backstop for everything else, including posts already stored that a backfill hands on.

    A different author handle alone is not enough. Creators change handles (Eric Verdin went from
    eric-verdin-490212 to eric-verdin-md) and their own posts then arrive under the new one, so a
    differing handle only counts when the author's name doesn't match the name we track them under
    either. When we can't tell (no handle, a member-ID URL, no name on file), the post is kept: a
    false drop would hide a real post, which is the thin-queue problem."""
    if raw.get("is_repost"):
        return True
    author = profile_slug(raw.get("author_profile_url") or "")
    source = profile_slug(source_ref or "")
    if not author or not source or author == source or author.startswith("acoa"):
        return False
    names = _tracked_names(db, source_ref)
    if not names:
        return False
    return not any(_same_person(raw.get("author_name") or "", n) for n in names)


def _score(client: Client, post: Post) -> None:
    score, reason, summary = score_post(client, post)
    post.relevance_score = score
    post.relevance_reason = reason
    post.summary = summary


def _save_and_process(db: Session, client: Client, source_ref: str, raw: dict) -> None:
    # Every path that stores and scores a post comes through here, so this is the backstop: an
    # archived client never gets a new post or a paid relevance call, whichever caller forgot.
    if client.archived:
        return
    # Never surface a client's own posts, or a same-company colleague's, in their feed.
    if is_own_or_colleague_post(db, client, raw.get("author_profile_url", ""), source_ref):
        # Still dropped from the feed, but first note the member ID, so a future handle change
        # is recognised. This is the only place a client's own post is seen.
        remember_member_id(db, client, raw.get("author_profile_url", ""))
        return
    if is_someone_elses_post(db, source_ref, raw):
        print(f"[discovery] skipped a repost from {source_ref}: {raw.get('author_name') or '?'} "
              f"{raw.get('post_url') or ''}")
        return
    existing = (db.query(Post)
                .filter(Post.client_id == client.id, Post.post_url == raw["post_url"]).first())
    if existing is not None:
        # Seen before. If its relevance call failed, score it now. An unscored post skips the
        # relevance floor (a failed call must not bury a good post), and nothing ever scored it
        # again, so every blip left a post in the feed for good, related to the client or not.
        # The same post comes back on the next fetch of that profile and on an Apify webhook
        # retry, so this costs one call per post that needs it and nothing otherwise.
        if existing.relevance_score is None and not existing.dismissed:
            _score(client, existing)
            db.commit()
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
        is_priority=_is_priority_creator(db, client.id, source_ref),
        language=detect_language(raw.get("content_snippet") or ""),
    )
    # Scored BEFORE the row is saved. It used to be saved, committed, then scored: a webhook that
    # ran out of time between the two (one profile fans out to every client tracking it, one paid
    # call each, inside a 60s function) left the post unscored, and so shown whatever it was
    # about. Now a post is in the feed only with its score, or with a failed score that the next
    # delivery retries (above).
    # Relevance is scored so the human can sort/filter; the reply text itself is
    # never generated until a person clicks "Draft reply". No auto-drafting here.
    _score(client, post)
    db.add(post)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # saved meanwhile by a concurrent delivery — dedup via the unique constraint
