from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.alerts import send_alert
from app.llm.relevance import score_post
from app.models import Burner, BurnerStatus, Client, Post
from app.scraper.creator_feed import fetch_recent_posts
from app.scraper.rate_limit import DailyCapReached, check_and_reserve_action, human_delay
from app.scraper.session import CheckpointDetected, burner_page
from app.jobs.health_check import redistribute_clients

# Keyword/topic search is intentionally NOT used here. LinkedIn checkpoints the
# whole session when automation touches /search/results/content/, which then
# blocks every other page too — including the watch-creator path below, which
# is otherwise reliable. Discovery is watch-list-only until that's solved.
#
# Each creator gets its OWN fresh browser session (a separate burner_page call),
# rather than one shared session hopping between several strangers' profiles.
# One session visiting many different profiles back-to-back is a stronger bot
# signal than several independent, freshly-launched sessions each visiting one —
# confirmed empirically: a shared-session batch degraded progressively (later
# creators failed more than earlier ones, ending in a hard checkpoint), while
# isolated single-creator sessions succeeded reliably.


def run_discovery_for_burner(db: Session, burner: Burner) -> None:
    if burner.status != BurnerStatus.active:
        return

    clients = db.query(Client).filter(Client.burner_id == burner.id).all()
    for client in clients:
        if burner.status != BurnerStatus.active:
            break
        _discover_for_client(db, burner, client)


def run_discovery_for_client(db: Session, client: Client) -> int:
    """Manual, on-demand sync for a single client (dashboard "Sync now" button).
    Returns the number of new posts found. Raises if the client has no active burner."""
    burner = client.burner
    if not burner or burner.status != BurnerStatus.active:
        raise RuntimeError("this client has no active burner assigned")

    before = db.query(Post).filter(Post.client_id == client.id).count()
    _discover_for_client(db, burner, client)
    after = db.query(Post).filter(Post.client_id == client.id).count()
    return after - before


def _discover_for_client(db: Session, burner: Burner, client: Client) -> None:
    for creator in client.watch_creators:
        if burner.status != BurnerStatus.active:
            return

        try:
            check_and_reserve_action(db, burner)
        except DailyCapReached:
            return

        try:
            with burner_page(burner) as page:
                posts = fetch_recent_posts(page, creator.profile_url, max_results=3)
        except CheckpointDetected as e:
            burner.status = BurnerStatus.needs_relogin
            db.commit()
            send_alert(f":warning: Burner '{burner.label}' checkpointed on {creator.label or creator.profile_url}: {e}")
            redistribute_clients(db, burner)
            return
        except Exception:
            # One creator's page misbehaving (timeout, anonymous render, layout quirk)
            # shouldn't sink the rest of the batch — skip it and keep going.
            human_delay()
            continue

        for raw in posts:
            raw["author_name"] = raw["author_name"] or creator.label
            _save_and_process(db, client, burner, creator.profile_url, raw)

        human_delay()


def _save_and_process(db: Session, client: Client, burner: Burner, source_ref: str, raw: dict) -> None:
    post = Post(
        client_id=client.id,
        burner_id=burner.id,
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

    # Relevance is scored automatically so the human has a hint to sort/filter by —
    # but the reply text itself is never generated until a person clicks "Draft reply"
    # on this specific post. No auto-drafting here.
    score, reason = score_post(client, post)
    post.relevance_score = score
    post.relevance_reason = reason
    db.commit()
