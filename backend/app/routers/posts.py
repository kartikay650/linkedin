import random
import re
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.llm.draft import (TWEAK_CHIPS, _sentences, angle_draft, generate_drafts, refine_draft,
                           shorten_draft, strip_unverifiable)
from app.llm.provenance import CHECK_FAILED_NOTE, annotate_provenance, check_failed, verify_claims
from app.llm.style import check_violations
from app.models import Client, ClientDocument, Draft, Post, TweakEvent, text_hash
from app.profiles import MEMBER_ID_SQL_PATTERN, own_identities
from app.scraper.apify_client import (LEGACY_CAP_UNTIL, LEGACY_POST_CHARS, MAX_POST_CHARS,
                                      account_usage)
from app.schemas import (DraftOut, DraftUpdate, ManualDraftRequest, PostTextOut, PostWithDrafts,
                         RefineDraftRequest)

router = APIRouter(tags=["posts"])

# Relevance floor (out of 10). Posts scoring below this are hidden from the feed and refused by the
# draft route: the scorer reliably marks them as posts the client can add nothing to, and commenting
# there reads as polite noise. The scorer's own distribution has a natural gap at 4-6, so 4 is a
# clean cut. Unscored posts and posts already carrying work are always kept.
MIN_DRAFT_RELEVANCE = 4
# Priority creators clear a slightly lower bar. Priority decides WHO gets a post; this decides
# whether it is worth commenting on at all, and the owner wanted a little more latitude for the
# eight accounts she named than for the rest of the list.
PRIORITY_MIN_RELEVANCE = 3


def _relevance_floor():
    """The relevance bar for a row: lower for a post from one of this client's priority creators."""
    return case((Post.is_priority, PRIORITY_MIN_RELEVANCE), else_=MIN_DRAFT_RELEVANCE)


# How much of a post body the feed ships per card. The card shows a gist under the one-line
# summary; the full text (up to MAX_POST_CHARS, for the drafter) is fetched for one post at a time
# by GET /posts/{id}/text, only when a reviewer clicks "Show full post".
_LIST_PREVIEW_CHARS = 450


def _flagged_claims(provenance) -> list[str]:
    """Claim spans that genuinely need removing. Excludes the 'safety check did not run' marker:
    that means the checker itself failed, so there is nothing to rewrite — the draft is shown as
    unverified for a human to look at instead."""
    return [
        s["text"] for s in (provenance or [])
        if s.get("level") == "unverified" and s.get("text")
        and CHECK_FAILED_NOTE not in (s.get("note") or "")
    ]


def _docs_text(db: Session, client_id: int) -> str:
    """Concatenated extracted text of the client's processed documents, used to
    ground the clinical-safety provenance check."""
    docs = (
        db.query(ClientDocument)
        .filter(ClientDocument.client_id == client_id, ClientDocument.status == "done")
        .all()
    )
    return "\n\n".join((d.extracted_text or "") for d in docs)


# Draft-status existence tests, reused by the feed query AND the count aggregates so a badge can
# never disagree with the tab it labels.
# "We have done work on this post, so never hide it." Includes 'posted' — that omission was a live
# bug: the age and relevance exemptions below both used a version limited to pending/drafted/
# approved, so a post whose only draft was already POSTED failed both branches once it aged past
# the 14-day window and silently left the Posted tab. 539 of 693 posted threads (78%) had already
# vanished that way, taking the record of delivered work with them. 'rejected' is deliberately not
# here: a rejected draft means the reviewer said no, so the post has no claim on staying visible.
_HAS_WORK = exists().where(and_(
    Draft.post_id == Post.id,
    Draft.status.in_(("pending", "drafted", "approved", "posted")),
))
_DRAFTED = exists().where(and_(Draft.post_id == Post.id, Draft.status == "drafted"))
_APPROVED = exists().where(and_(Draft.post_id == Post.id, Draft.status == "approved"))
_POSTED = exists().where(and_(Draft.post_id == Post.id, Draft.status == "posted"))

# A post reaches at most this many client feeds — the two scoring highest for it. The same
# LinkedIn post was being served to up to 8 client feeds at once, so one author collected comments
# from most of the roster and their audience noticed ("we're all commenting under the same
# accounts, my clients are flagging it").
MAX_FEEDS_PER_POST = 2

# Grandfather clause: ANY draft at all, including rejected. Wider than _HAS_WORK on purpose — a
# post the reviewer has already looked at should not be re-ranked out from under them.
_HAS_ANY_DRAFT = exists().where(Draft.post_id == Post.id)


def _within_feed_quota():
    """True when this row is one of the MAX_FEEDS_PER_POST highest-scoring feeds for its post_url,
    or already carries work.

    Counts the rows that rank strictly AHEAD of this one rather than computing a rank, so it reads
    as a plain SQL condition and composes into _visible_conditions with everything else. Ties break
    on client_id so the ordering is deterministic and a feed cannot flicker between loads.
    Costs ~22ms across the whole table given the posts(post_url) index; without that index it was
    568ms, which is why the migration alongside this adds it."""
    other = aliased(Post)
    mine = func.coalesce(Post.relevance_score, -1.0)
    theirs = func.coalesce(other.relevance_score, -1.0)
    # Ordering key is (is_priority, relevance, client_id). Priority comes FIRST so a client given
    # first claim on a creator keeps a slot even when two other clients score the post higher —
    # that is the whole point of the flag. The second slot still goes to the next-best client.
    ahead = (
        select(func.count())
        .select_from(other)
        .where(
            other.post_url == Post.post_url,
            other.dismissed.is_(False),
            other.client_id != Post.client_id,
            or_(
                and_(other.is_priority.is_(True), Post.is_priority.is_(False)),
                and_(other.is_priority == Post.is_priority, theirs > mine),
                and_(other.is_priority == Post.is_priority, theirs == mine,
                     other.client_id < Post.client_id),
            ),
        )
        .scalar_subquery()
    )
    return or_(ahead < MAX_FEEDS_PER_POST, _HAS_ANY_DRAFT)


# The per-view predicates, in SQL. These define what each tab contains.
_VIEW_SQL = {
    "posted": _POSTED,
    "approved": and_(_APPROVED, ~_POSTED),
    "draft": and_(_DRAFTED, ~_APPROVED, ~_POSTED),
    "needs_review": and_(~_APPROVED, ~_POSTED),
    "active": and_(~_DRAFTED, ~_APPROVED, ~_POSTED),
}


def _visible_conditions(db: Session, client_id: int, max_age_days: int):
    """The 'is this post in the client's feed at all' rules, as SQL conditions: not dismissed,
    fresh enough (or carrying work), above the relevance floor (or unscored/carrying work), not written
    by the client themselves or a same-company colleague, and among the top MAX_FEEDS_PER_POST
    client feeds for that post.

    Shared by the feed query and the count/summary aggregates so all three agree by construction.
    The author exclusion mirrors profiles.is_own_or_colleague_post(): handle or member ID, in SQL."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max_age_days)
    dt = func.coalesce(Post.posted_at, Post.fetched_at)
    conds = [
        Post.client_id == client_id,
        Post.dismissed.is_(False),
        or_(dt >= cutoff, _HAS_WORK),
        # English only. A comment drafted in German under a German post is not something any
        # client will post, so these are noise in the queue. _HAS_WORK is the escape hatch: a post
        # somebody already drafted or posted on stays visible whatever language it is in, so this
        # can never retroactively hide delivered work.
        or_(Post.language == "en", Post.language.is_(None), _HAS_WORK),
        or_(Post.relevance_score.is_(None),
            func.round(Post.relevance_score * 10) >= _relevance_floor(), _HAS_WORK),
        _within_feed_quota(),
    ]
    client = db.get(Client, client_id)
    handles, ids = own_identities(db, client) if client else (set(), set())
    # Author handle, source handle and author member ID are each checked on their own. The old
    # coalesce(author, source) only looked at the source when the author had no handle, and
    # matched handles only, so a client who changed handle saw their own posts. Every term is
    # coalesced to '' because NOT (NULL IN (...)) is NULL, which would silently hide the row.
    own = []
    if handles:
        for col in (Post.author_profile_url, Post.source_ref):
            h = func.coalesce(func.substring(func.lower(func.coalesce(col, "")), r"/in/([^/?#]+)"), "")
            own.append(h.in_(list(handles)))
    if ids:
        mid = func.coalesce(func.substring(func.coalesce(Post.author_profile_url, ""),
                                           MEMBER_ID_SQL_PATTERN), "")
        own.append(mid.in_(list(ids)))
    if own:
        conds.append(~or_(*own))
    return conds


def _paged_posts(db: Session, client_id: int, view: str, max_age_days: int,
                 limit: int, offset: int) -> list[Post]:
    """Egress-lean feed read: apply recency + relevance + the requested VIEW filter in SQL and
    paginate, so the backend fetches only the page actually shown instead of the client's entire
    post set (the old path pulled all ~900 rows on every load/tab-switch — the main egress hog).
    Drafts for the page load via selectinload (one extra IN query — pagination-safe)."""
    dt = func.coalesce(Post.posted_at, Post.fetched_at)
    posted = _POSTED

    q = db.query(Post).filter(*_visible_conditions(db, client_id, max_age_days))
    if view == "posted":
        q = q.filter(posted)
    elif view in _VIEW_SQL:
        q = q.filter(_VIEW_SQL[view])
    # "all" adds no view filter

    # newest DAY first, then most-relevant within the day, then newest time (matches _order_key)
    posts = (
        q.order_by(func.date(dt).desc(), Post.relevance_score.desc().nullslast(), dt.desc())
        .options(selectinload(Post.drafts))
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
        .all()
    )
    # Ship a PREVIEW of the post body, not the whole thing. Posts are now stored up to 2500 chars
    # (needed so the drafter sees the full argument), but the card only shows a gist above the
    # one-line summary, and "Show full post" fetches the rest for that one card. Sending the full
    # body for every card would have made the feed ~4x heavier than before.
    #
    # EXPUNGE FIRST: these instances are only being serialised into the response, and trimming the
    # attribute on a session-attached row would mark it dirty — a later flush would then write the
    # truncated text back and permanently destroy the post body. Detaching makes that impossible.
    # The drafting routes read their own Post row, so they still get the full text.
    db.expunge_all()
    for p in posts:
        body = p.content_snippet or ""
        if len(body) > _LIST_PREVIEW_CHARS:
            p.content_snippet = body[:_LIST_PREVIEW_CHARS].rstrip() + "…"
            p.preview_truncated = True  # read by PostOut; not a column, and p is detached
        # Slim the provenance trace the same way. The card only renders a count of grounded
        # spans plus the flagged ones (short quote + source link) — the full text and the
        # per-span notes of every grounded span are downloaded and never shown. Single-draft
        # responses (refine, verify-claims) still return the complete trace.
        for d in p.drafts:
            segs = d.provenance if isinstance(d.provenance, list) else []
            d.provenance = [
                {"level": s.get("level"),
                 "text": (s.get("text") or "")[:70],
                 "source_url": s.get("source_url", ""),
                 # The one note the card needs: "the check didn't run" (Draft.check_failed).
                 **({"note": CHECK_FAILED_NOTE} if CHECK_FAILED_NOTE in (s.get("note") or "") else {})}
                if s.get("level") in ("unverified", "contradicted")
                else {"level": s.get("level")}
                for s in segs if isinstance(s, dict)
            ]
    return posts


@router.get("/clients/{client_id}/posts", response_model=list[PostWithDrafts])
def list_posts_for_client(
    client_id: int,
    view: str = Query("active", description="active | needs_review | approved | posted | all"),
    max_age_days: int = Query(14, description="only show posts newer than this many days"),
    limit: int = Query(60, ge=1, le=200, description="page size"),
    offset: int = Query(0, ge=0, description="pagination offset"),
    db: Session = Depends(get_db),
):
    return _paged_posts(db, client_id, view, max_age_days, limit, offset)


@router.get("/clients/{client_id}/post-counts")
def post_counts(
    client_id: int,
    max_age_days: int = Query(14, description="same window as the post list"),
    db: Session = Depends(get_db),
):
    """Per-tab counts for the badge on each tab (Queue/Draft/Approved/Posted/All).

    Pure SQL aggregate: the database returns five integers instead of shipping every post row
    (plus its drafts) to the app just to be counted in Python. Uses the same _visible_conditions
    and _VIEW_SQL as the list, so a badge can't disagree with its tab."""
    conds = _visible_conditions(db, client_id, max_age_days)
    row = db.query(
        func.count().filter(_VIEW_SQL["active"]).label("active"),
        func.count().filter(_VIEW_SQL["draft"]).label("draft"),
        func.count().filter(_VIEW_SQL["approved"]).label("approved"),
        func.count().filter(_VIEW_SQL["posted"]).label("posted"),
        func.count().label("all"),
    ).select_from(Post).filter(*conds).one()
    return {"active": row.active, "draft": row.draft, "approved": row.approved,
            "posted": row.posted, "all": row.all}


# Alert thresholds for the notification badge/pop-up. to_approve is set high because a large
# review backlog is normal — a low number would fire constantly. Tune here.
_NOTIFY_THRESHOLDS = {
    "to_post": {"count": 10, "hours": 24},    # approved & waiting for the poster
    "to_approve": {"count": 40, "hours": 48},  # drafted & waiting for the approver
}


@router.get("/notifications/summary")
def notifications_summary(
    max_age_days: int = Query(14, description="same window as the post list"),
    db: Session = Depends(get_db),
):
    """Agency-wide 'what's waiting' for the notification badge + pop-up. Per stage
    (to_post = approved-not-posted; to_approve = drafted-not-approved): the total across ALL
    clients, the oldest waiting item's age, and a per-client breakdown so a click can jump
    straight to the right client's tab. Same visible/in-view logic as the tabs, so the
    numbers always match. Age uses the draft's created_at (best available proxy for how long
    it's been sitting — there's no status-change timestamp).

    Computed as SQL aggregates per client (counts + the oldest waiting draft's timestamp). This
    endpoint is polled by every open dashboard, and it used to load every visible post row and its
    drafts for all 8 clients on each poll (~250kB a call, tens of MB a day) purely to produce a
    handful of numbers. Now the database returns the numbers."""
    now = datetime.now(timezone.utc)
    # stage key -> (view predicate, the draft status whose age we measure)
    STAGE = {"to_post": ("approved", "approved"), "to_approve": ("draft", "drafted")}
    result = {k: {"total": 0, "oldest_hours": None, "by_client": []} for k in STAGE}

    for client in db.query(Client).order_by(Client.name).all():
        conds = _visible_conditions(db, client.id, max_age_days)
        for key, (view, status) in STAGE.items():
            # Two scalar aggregates. Deliberately NOT one joined query: the view predicates are
            # EXISTS subqueries over drafts, so joining drafts into the outer query makes
            # SQLAlchemy correlate both tables away and emit an invalid statement. Selecting the
            # matching post ids first keeps each statement simple and valid.
            n = db.query(func.count()).select_from(Post).filter(*conds, _VIEW_SQL[view]).scalar()
            if not n:
                continue
            ids = db.query(Post.id).filter(*conds, _VIEW_SQL[view]).scalar_subquery()
            oldest = (
                db.query(func.min(Draft.created_at))
                .filter(Draft.status == status, Draft.post_id.in_(ids))
                .scalar()
            )
            oh = None
            if oldest:
                ts = oldest if oldest.tzinfo else oldest.replace(tzinfo=timezone.utc)
                oh = round((now - ts).total_seconds() / 3600, 1)
            result[key]["total"] += n
            result[key]["by_client"].append(
                {"id": client.id, "name": client.name, "count": n, "oldest_hours": oh}
            )
            if oh is not None and (result[key]["oldest_hours"] is None or oh > result[key]["oldest_hours"]):
                result[key]["oldest_hours"] = oh
    for k in result:
        result[k]["by_client"].sort(key=lambda x: x["count"], reverse=True)
    return {**result, "thresholds": _NOTIFY_THRESHOLDS}


@router.post("/posts/{post_id}/dismiss")
def dismiss_post(post_id: int, db: Session = Depends(get_db)):
    """Remove a post from the feed without replying to it."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post not found")
    post.dismissed = True
    db.commit()
    return {"ok": True}


@router.get("/posts/{post_id}/text", response_model=PostTextOut)
def post_text(post_id: int, db: Session = Depends(get_db)):
    """The whole stored text of one post, for "Show full post" on the card. The feed ships only a
    preview, so this is the one place the browser gets the full body, and only for the card a
    reviewer opened.

    `truncated` says the stored text was itself cut at scrape time (apify_client.MAX_POST_CHARS,
    or LEGACY_POST_CHARS for posts published before LEGACY_CAP_UNTIL), so the end exists only on
    LinkedIn. It is inferred from the length, as nothing records it: a post that happens to be
    exactly that long is flagged too, which only adds a "read the rest on LinkedIn" note. The date
    is posted_at (kept when backfill copies a post to another client), else fetched_at."""
    row = (db.query(Post.content_snippet, func.coalesce(Post.posted_at, Post.fetched_at))
           .filter(Post.id == post_id).first())
    if row is None:
        raise HTTPException(404, "post not found")
    text, dt = row[0] or "", row[1]
    if dt is not None and dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    legacy = len(text) == LEGACY_POST_CHARS and dt is not None and dt < LEGACY_CAP_UNTIL
    return {"id": post_id, "text": text, "truncated": len(text) >= MAX_POST_CHARS or legacy}


@router.get("/apify-usage")
def apify_usage():
    """Per-account Apify spend vs monthly credit, for the expense tracker."""
    return account_usage()


# A comment that ends ", Name." is the sign-off reviewers keep deleting. 56 of Silvana's 161 posted
# edits end that way, so without this filter the examples would teach it straight back.
_SIGNOFF_RE = re.compile(r",\s+(?:Dr\.?\s+)?[A-Z][\w'\u2019-]+\.?\s*$")
_MAX_EXAMPLES = 5
_MIN_EXAMPLES = 3
# An "edit" that keeps 90%+ of the tool's text (a dropped full stop, one word swapped) is the
# tool's own output with a touch-up, and would teach the drafter its own patterns back.
_NEAR_COPY = 0.9


def _approved_examples(db: Session, post: Post) -> list[str]:
    """Comments for this client that a HUMAN edited before approving or posting them.

    The examples used to be the client's last 8 approved comments, edited or not. For Dr. Joe
    Raffaele all 8 were the tool's own unedited output, so the drafter was learning from itself and
    every pattern it had compounded. Now a comment qualifies only when:
      - it was approved or posted, and someone substantively changed its text first (edited_text
        keeps less than 90% of what the tool last wrote);
      - it is not paste-marked. Generated text never ends in whitespace, and about half of the
        posted edits do, which looks like a rewrite pasted in from elsewhere (ChatGPT is the open
        question in BACKLOG.md). Those are left out until that is answered;
      - it passes the hard house-style bans (stacked statements excepted: that gate also fires on
        the owner's own GOOD examples) and has no ", Name." sign-off.
    At most five, rotated by post so no single example is shown on every draft, and none at all
    when fewer than three qualify: two examples are copied rather than learned from."""
    rows = (
        db.query(Draft.text, Draft.edited_text)
        .join(Post, Post.id == Draft.post_id)
        .filter(Post.client_id == post.client_id, Draft.post_id != post.id,
                Draft.source == "generated",
                Draft.status.in_(["approved", "posted"]), Draft.edited_text.isnot(None))
        .order_by(Draft.created_at.desc()).limit(60).all()
    )
    norm = lambda t: " ".join((t or "").split()).lower()
    picked: list[str] = []
    for text, edited in rows:
        if not edited or edited != edited.rstrip():  # empty, or paste-marked
            continue
        e = edited.strip()
        if norm(e) == norm(text) or e in picked:  # unedited tool output, or a duplicate
            continue
        if SequenceMatcher(None, norm(e), norm(text)).ratio() >= _NEAR_COPY:
            continue
        if _SIGNOFF_RE.search(e):
            continue
        if any(not v.startswith("stacked statements") for v in check_violations(e)):
            continue
        picked.append(e)
    if len(picked) < _MIN_EXAMPLES:
        return []
    return random.Random(post.id).sample(picked, min(_MAX_EXAMPLES, len(picked)))


def _draft_context(db: Session, post: Post):
    """Shared anti-repetition context for BOTH drafting and refining, so a Tweak gets the same
    guardrail inputs as a fresh Draft: (recent) this client's recent drafts to avoid; (global) a
    cross-client sample for the self-aware profile; (approved) comments a human edited for this
    client (voice only, see _approved_examples); (siblings) comments OTHER profiles already made on
    this SAME post.

    recent and global are read from original_text, what the tool actually wrote. `text` is
    overwritten by every Tweak, so a question that the reviewer removed with "No question" vanished
    from the pattern stats the drafter uses to stop repeating itself, and the tool never learned it
    was over-asking. Rows from before original_text existed fall back to text. Comments a reviewer
    wrote by hand are not the tool's output, so they are left out of both."""
    wrote = func.coalesce(Draft.original_text, Draft.text)
    recent = [
        r[0] for r in db.query(wrote)
        .join(Post, Post.id == Draft.post_id)
        .filter(Post.client_id == post.client_id, Draft.post_id != post.id,
                Draft.source == "generated")
        .order_by(Draft.created_at.desc()).limit(20).all()
    ]
    global_recent = [
        r[0] for r in db.query(wrote)
        .filter(Draft.post_id != post.id, Draft.source == "generated")
        .order_by(Draft.created_at.desc()).limit(40).all()
    ]
    approved = _approved_examples(db, post)
    siblings: list[str] = []
    if post.post_url:
        seen = set()
        for d in (
            db.query(Draft).join(Post, Post.id == Draft.post_id)
            .filter(Post.post_url == post.post_url, Post.client_id != post.client_id)
            .order_by(Draft.created_at.desc()).limit(12).all()
        ):
            t = (d.edited_text or d.text or "").strip()
            if t and t not in seen:
                seen.add(t)
                siblings.append(t)
        siblings = siblings[:8]
    return recent, global_recent, approved, siblings


def _safety_pass(client: Client, post: Post, text: str, docs_text: str):
    """Provenance + the 'nothing to fact-check' enforcement for one piece of tool-written text.
    Every path that puts new tool text on a card (draft, Tweak, Different angle) runs this, so no
    path can skip it. No DB access, so it is safe in a worker thread."""
    provenance = annotate_provenance(client, post, text, docs_text)
    flagged = _flagged_claims(provenance)
    if flagged:
        safer = strip_unverifiable(client, post, text, flagged)
        if safer and safer != text:
            text = safer
            provenance = annotate_provenance(client, post, text, docs_text)
    return text, provenance


def _checked_hash(provenance, text: str) -> str | None:
    """The hash recording which text was fact-checked, or None when the check didn't run, so a
    failed check is never mistaken for a fresh one."""
    return None if check_failed(provenance) else text_hash(text)


def _norm(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _human_edited(d: Draft) -> bool:
    """Someone typed into this option: a hand-written comment, or a saved edit to a generated one."""
    return d.source == "manual" or bool(d.edited_text and _norm(d.edited_text) != _norm(d.text))


def _set_aside(db: Session, d: Draft) -> None:
    """Remove an option from the card. Human writing is kept as a rejected row rather than
    deleted, so a click on a different option can never destroy it; tool text is deleted."""
    if _human_edited(d):
        d.status = "rejected"
    else:
        db.delete(d)


def _log_tweak(db: Session, draft: Draft, post: Post, chip: str | None, instruction: str,
               before: str) -> None:
    db.add(TweakEvent(client_id=post.client_id, post_id=post.id, draft_id=draft.id, chip=chip,
                      instruction=None if chip else (instruction or "")[:500], before_text=before))


@router.post("/posts/{post_id}/draft", response_model=list[DraftOut])
def draft_reply(post_id: int, db: Session = Depends(get_db)):
    """Generate reply drafts for a post — only ever called explicitly by a human
    clicking 'Draft reply', never automatically during discovery."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post not found")

    # Relevance gate. The scorer already identifies posts a client can add nothing to, but nothing
    # used to stop a writer drafting on them anyway — 48% of all drafting went to posts under 4/10,
    # and every comment the reviewer rejected as "not worth my time" came from that band. Refuse
    # server-side so the rule can't be clicked past.
    # Regenerating an EXISTING draft is allowed even below the bar: those drafts were written by the
    # old pipeline and the team needs to be able to replace a bad one rather than being stuck with it.
    # The bar only blocks starting NEW work on a post nobody has drafted for.
    already_drafted = any(d.status != "rejected" for d in post.drafts)
    if (
        not already_drafted
        and post.relevance_score is not None
        and round(post.relevance_score * 10) < (PRIORITY_MIN_RELEVANCE if post.is_priority
                                                 else MIN_DRAFT_RELEVANCE)
    ):
        raise HTTPException(
            422,
            f"This post scored {round(post.relevance_score * 10)}/10 for {post.client.name} — below the "
            f"{PRIORITY_MIN_RELEVANCE if post.is_priority else MIN_DRAFT_RELEVANCE}/10 bar, so a "
            "comment would be polite noise rather than value. "
            "Skip it, or raise its relevance if the score looks wrong.",
        )

    recent, global_recent, approved, siblings = _draft_context(db, post)

    # Two DIVERSE candidates so the reviewer picks the angle they like (acting on one
    # auto-discards the other — see update_draft).
    texts = generate_drafts(post.client, post, count=2, avoid_texts=recent, voice_examples=approved,
                            global_texts=global_recent, sibling_texts=siblings)
    if not texts:
        raise HTTPException(502, "draft generation failed — try again")

    # Replace any existing non-posted GENERATED options so regenerating never stacks up copies. A
    # comment the reviewer wrote by hand stays on the card: Regenerate asks for new tool options,
    # never for deleting her writing. A generated option she edited leaves the card but is kept
    # as a rejected row rather than deleted (the dashboard asks before it happens).
    for d in list(post.drafts):
        if d.status == "posted" or d.source == "manual":
            continue
        if d.status == "rejected" and _human_edited(d):
            continue
        _set_aside(db, d)
    db.flush()

    docs_text = _docs_text(db, post.client_id)
    client = post.client
    # Force-load the attributes the safety pass reads, so the worker threads below never trigger a
    # lazy DB load off the session (SQLAlchemy sessions are not thread-safe).
    _ = (client.name, client.voice_samples, client.viewpoints, client.key_messages,
         client.guardrails, post.content_snippet)

    def _safe(text: str):
        return _safety_pass(client, post, text, docs_text)

    # Run the candidates' safety passes CONCURRENTLY: serially they made a two-candidate draft
    # ~60s (the serverless ceiling); in parallel the cost is the slowest one, not the sum.
    try:
        with ThreadPoolExecutor(max_workers=min(len(texts), 3)) as ex:
            results = list(ex.map(_safe, texts))
    except Exception:
        results = [_safe(t) for t in texts]

    created = []
    for i, (text, provenance) in enumerate(results):
        # No quality label any more. The drafter now runs a dedicated repair pass (_fuse) when a
        # comment still reads as bolted-together statements, so the fix happens instead of being
        # handed to the reviewer as "AI could not get this one right". The label also misfired on
        # genuinely good short replies, which cost more trust than it saved.
        draft = Draft(post_id=post.id, variant_index=i, text=text, original_text=text,
                      provenance=provenance, provenance_hash=_checked_hash(provenance, text))
        db.add(draft)
        created.append(draft)
    db.commit()
    for d in created:
        db.refresh(d)
    return created


@router.post("/drafts/{draft_id}/refine", response_model=DraftOut)
def refine_draft_route(draft_id: int, payload: RefineDraftRequest, db: Session = Depends(get_db)):
    """Rewrite a draft per a Tweak chip (sent by id) or a free-text instruction, keeping it in the
    client's voice and through the same gates and safety pass as a first draft."""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    chip = (payload.chip or "").strip() or None
    if chip is not None and chip not in TWEAK_CHIPS:
        raise HTTPException(422, f"unknown tweak '{chip}'")
    if chip == "angle":
        raise HTTPException(422, "use POST /drafts/{id}/angle for a different angle")
    instruction = TWEAK_CHIPS[chip] if chip else (payload.instruction or "").strip()
    if not instruction:
        raise HTTPException(422, "say how to change it, or pick a tweak")
    if draft.status == "posted":
        raise HTTPException(409, "this comment is already posted on LinkedIn")
    if draft.source == "manual":
        raise HTTPException(409, "this comment was written by hand; edit it directly")
    post = db.get(Post, draft.post_id)
    current = draft.edited_text or draft.text
    # Same anti-repetition context as a fresh draft, so a Tweak is fully guarded too (no more
    # 'Curious'/praise-slop leaking back in through the refine path).
    recent, global_recent, approved, siblings = _draft_context(db, post)
    context = dict(avoid_texts=recent, voice_examples=approved, global_texts=global_recent,
                   sibling_texts=siblings)
    if chip == "shorter":
        revised = shorten_draft(post.client, post, current, **context)
    else:
        revised = refine_draft(post.client, post, current, instruction, **context)
    if not (revised or "").strip():
        # The model call failed. This used to hand back her own text as if it were the tweak,
        # then run it through the fact-check rewrite and log a tweak that never happened.
        raise HTTPException(502, "couldn't rewrite that one — try again")
    if _norm(revised) == _norm(current):
        return draft  # nothing to change (e.g. "No question" on a statement): leave it as it is
    docs_text = _docs_text(db, post.client_id)
    if draft.edited_text and _norm(revised) in {_norm(x) for x in _sentences(current)}:
        # Shorter kept one of HER sentences word for word. Human text is flagged, never rewritten.
        provenance = annotate_provenance(post.client, post, revised, docs_text)
    else:
        # Enforce "nothing to fact-check" on the TWEAK path too. A tweak is a prime way for an
        # unverifiable claim to come back, and previously this route only re-labelled it.
        revised, provenance = _safety_pass(post.client, post, revised, docs_text)
    _log_tweak(db, draft, post, chip, instruction, current)
    draft.text = revised
    # original_text is deliberately NOT touched here. It is the only record of what the tool
    # actually produced, and this line is what used to destroy it.
    draft.edited_text = None  # revised text supersedes prior manual edits
    draft.provenance = provenance
    draft.provenance_hash = _checked_hash(provenance, revised)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/drafts/{draft_id}/angle", response_model=DraftOut)
def angle_draft_route(draft_id: int, db: Session = Depends(get_db)):
    """Replace one option with a comment on a different angle from everything already shown for
    this post: this option as it stands, what the tool first wrote for it, and the other options.
    A new first draft for this option, so original_text is reset to it."""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    if draft.status == "posted":
        raise HTTPException(409, "this comment is already posted on LinkedIn")
    if draft.source == "manual":
        raise HTTPException(409, "this comment was written by hand; edit it directly")
    if draft.status == "approved":
        # A different angle is a new comment the approver never saw, so it can't stay "approved".
        raise HTTPException(409, "this comment is approved; move it back to draft for a new angle")
    post = db.get(Post, draft.post_id)
    current = draft.edited_text or draft.text
    taken = [current, draft.text, draft.original_text] + [
        d.edited_text or d.text for d in post.drafts
        if d.id != draft.id and d.status in ("pending", "drafted", "approved")
    ]
    taken = list(dict.fromkeys(t.strip() for t in taken if t and t.strip()))
    recent, global_recent, approved, siblings = _draft_context(db, post)
    text = angle_draft(post.client, post, taken, avoid_texts=recent, voice_examples=approved,
                       global_texts=global_recent, sibling_texts=siblings)
    if not text:
        raise HTTPException(502, "couldn't write a different angle — try again")
    text, provenance = _safety_pass(post.client, post, text, _docs_text(db, post.client_id))
    _log_tweak(db, draft, post, "angle", "", current)
    draft.text = text
    draft.original_text = text
    draft.edited_text = None
    draft.provenance = provenance
    draft.provenance_hash = _checked_hash(provenance, text)
    db.commit()
    db.refresh(draft)
    return draft


# One fact-check call on its own serverless invocation: no retry, so a slow check can't cross the
# 60s limit. A timeout fails closed (shown as "safety check did not run").
_LONE_CHECK_TIMEOUT = 25.0
_MANUAL_MAX_CHARS = 3000


@router.post("/posts/{post_id}/manual-draft", response_model=DraftOut)
def manual_draft(post_id: int, payload: ManualDraftRequest, db: Session = Depends(get_db)):
    """Save a comment the reviewer wrote herself ("Write my own").

    Saved BEFORE it is fact-checked, carrying the fail-closed "safety check did not run" marker,
    so her text is never lost to a slow check and never shows as checked when it wasn't. Then one
    bounded check replaces the marker. Never passed to strip_unverifiable: the tool does not
    rewrite a human's comment, it only flags what in it would need checking. original_text stays
    empty because the tool wrote none of it."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post not found")
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(422, "write the comment first")
    if len(text) > _MANUAL_MAX_CHARS:
        raise HTTPException(422, f"that's longer than a LinkedIn comment should be ({_MANUAL_MAX_CHARS} characters max)")
    # Saving twice (a retry after a slow check timed out, a double click) returns the comment
    # already saved instead of adding a duplicate option.
    for d in post.drafts:
        if d.source == "manual" and d.status == "pending" and _norm(d.text) == _norm(text):
            return d
    used = [d.variant_index or 0 for d in post.drafts]
    draft = Draft(post_id=post.id, variant_index=(max(used) + 1) if used else 0, text=text,
                  original_text=None, source="manual", status="pending",
                  provenance=[{"text": text, "level": "unverified", "note": CHECK_FAILED_NOTE,
                               "source_url": ""}])
    db.add(draft)
    db.commit()
    db.refresh(draft)
    provenance = annotate_provenance(post.client, post, text, _docs_text(db, post.client_id),
                                     timeout=_LONE_CHECK_TIMEOUT, max_retries=0)
    draft.provenance = provenance
    draft.provenance_hash = _checked_hash(provenance, text)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/drafts/{draft_id}/recheck", response_model=DraftOut)
def recheck_draft(draft_id: int, db: Session = Depends(get_db)):
    """Re-run the fact-check on the text the card shows now, after an edit. Flags only: an edited
    comment is human text, so nothing here rewrites it."""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    post = db.get(Post, draft.post_id)
    shown = draft.edited_text or draft.text
    provenance = annotate_provenance(post.client, post, shown, _docs_text(db, post.client_id),
                                     timeout=_LONE_CHECK_TIMEOUT, max_retries=0)
    draft.provenance = provenance
    draft.provenance_hash = _checked_hash(provenance, shown)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/drafts/{draft_id}/verify-claims", response_model=DraftOut)
def verify_claims_route(draft_id: int, db: Session = Depends(get_db)):
    """Web-verify the flagged (unverified) clinical/statistical claims in a draft
    and attach sources. Slow (web search) — called explicitly, never during drafting."""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")

    segments = list(draft.provenance or [])
    # The "check didn't run" marker is the whole comment, not a claim. Web-searching it as one
    # claim could mark an unchecked comment "grounded"; Re-check is the fix for that state.
    flagged_segs = [s for s in segments if s.get("level") == "unverified"
                    and CHECK_FAILED_NOTE not in (s.get("note") or "")][:2]
    if not flagged_segs:
        return draft

    results = verify_claims(draft.edited_text or draft.text, [s["text"] for s in flagged_segs])
    # Fold verdicts back by order (results are index-aligned to flagged_segs).
    for seg, r in zip(flagged_segs, results):
        verdict = r.get("verdict")
        seg["source_url"] = r.get("source_url", "")
        if r.get("note"):
            seg["note"] = r["note"]
        if verdict == "supported":
            seg["level"] = "grounded"
        elif verdict == "contradicted":
            seg["level"] = "contradicted"
        # "unconfirmed" stays "unverified"

    draft.provenance = segments
    flag_modified(draft, "provenance")  # in-place JSON edits aren't auto-detected
    db.commit()
    db.refresh(draft)
    return draft


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    """Remove one draft option (used to discard the option you don't want, leaving the
    other for the next person in the drafter -> approver -> poster handoff)."""
    draft = db.get(Draft, draft_id)
    if draft:
        db.delete(draft)
        db.commit()
    return {"ok": True}


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
    """Save an edit and/or a status. Returns the draft, so the card learns straight away whether
    the saved edit has left its fact-check stale."""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")

    if payload.edited_text is not None:
        draft.edited_text = payload.edited_text
    if payload.status is not None:
        draft.status = payload.status
        # Picking a candidate (move to draft / approve / mark posted) discards the other
        # un-picked options on the same post so a post never carries a leftover candidate.
        if payload.status in ("drafted", "approved", "posted"):
            for sib in db.query(Draft).filter(
                Draft.post_id == draft.post_id, Draft.id != draft.id, Draft.status == "pending"
            ).all():
                _set_aside(db, sib)  # a hand-written or edited option is kept as rejected

    db.commit()
    db.refresh(draft)
    return draft
