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

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.llm.relevance import score_post
from app.models import Client, Post
from app.scraper.apify_client import ApifyError, _build_input, fetch_posts as apify_fetch_posts, start_actor


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
    """Webhook mode: start one actor run per watch-creator with a callback, and
    return how many were started. Posts arrive later via /apify/webhook."""
    started = 0
    for creator in client.watch_creators:
        payload = _build_input(creator.profile_url, 3)
        webhook = _build_webhook(client.id, creator.label or "", creator.profile_url)
        try:
            start_actor(settings.apify_actor_id, payload, webhook=webhook)
            started += 1
        except ApifyError as e:
            print(f"[apify] couldn't start run for {creator.label or creator.profile_url}: {e}")
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
