from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.llm.draft import generate_drafts, refine_draft, strip_unverifiable
from app.llm.provenance import CHECK_FAILED_NOTE, annotate_provenance, verify_claims
from app.models import Client, ClientDocument, Draft, Post
from app.profiles import excluded_author_slugs
from app.scraper.apify_client import account_usage
from app.schemas import DraftOut, DraftUpdate, PostWithDrafts, RefineDraftRequest

router = APIRouter(tags=["posts"])

# Relevance floor (out of 10). Posts scoring below this are hidden from the feed and refused by the
# draft route: the scorer reliably marks them as posts the client can add nothing to, and commenting
# there reads as polite noise. The scorer's own distribution has a natural gap at 4-6, so 4 is a
# clean cut. Unscored posts and posts already carrying work are always kept.
MIN_DRAFT_RELEVANCE = 4

# How much of a post body the feed ships per card. The card shows a gist under the one-line
# summary; the full text (now up to 2500 chars, for the drafter) never needs to reach the browser.
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
_WORKING = exists().where(and_(Draft.post_id == Post.id, Draft.status.in_(("pending", "drafted", "approved"))))
_DRAFTED = exists().where(and_(Draft.post_id == Post.id, Draft.status == "drafted"))
_APPROVED = exists().where(and_(Draft.post_id == Post.id, Draft.status == "approved"))
_POSTED = exists().where(and_(Draft.post_id == Post.id, Draft.status == "posted"))

# A post reaches at most this many client feeds — the two scoring highest for it. The same
# LinkedIn post was being served to up to 8 client feeds at once, so one author collected comments
# from most of the roster and their audience noticed ("we're all commenting under the same
# accounts, my clients are flagging it").
MAX_FEEDS_PER_POST = 2

# Grandfather clause. Deliberately ANY draft, not _WORKING: _WORKING omits 'posted', so a post
# whose comment is already live would drop out of the Posted tab the moment this rule shipped.
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
    ahead = (
        select(func.count())
        .select_from(other)
        .where(
            other.post_url == Post.post_url,
            other.dismissed.is_(False),
            other.client_id != Post.client_id,
            or_(theirs > mine, and_(theirs == mine, other.client_id < Post.client_id)),
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
    fresh enough (or carrying work), above the relevance floor (or unscored/working), not written
    by the client themselves or a same-company colleague, and among the top MAX_FEEDS_PER_POST
    client feeds for that post.

    Shared by the feed query and the count/summary aggregates so all three agree by construction.
    The author exclusion mirrors profiles.profile_slug(): pull '/in/<slug>' out of the URL in SQL."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max_age_days)
    dt = func.coalesce(Post.posted_at, Post.fetched_at)
    conds = [
        Post.client_id == client_id,
        Post.dismissed.is_(False),
        or_(dt >= cutoff, _WORKING),
        or_(Post.relevance_score.is_(None),
            func.round(Post.relevance_score * 10) >= MIN_DRAFT_RELEVANCE, _WORKING),
        _within_feed_quota(),
    ]
    client = db.get(Client, client_id)
    excluded = excluded_author_slugs(db, client) if client else set()
    if excluded:
        slug = func.coalesce(
            func.substring(func.lower(func.coalesce(Post.author_profile_url, "")), r"/in/([^/?#]+)"),
            func.substring(func.lower(func.coalesce(Post.source_ref, "")), r"/in/([^/?#]+)"),
            "",
        )
        conds.append(~slug.in_(list(excluded)))
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
    # one-line summary, and "Open post" goes to LinkedIn for the rest. Sending the full body for
    # every card would have made the feed ~4x heavier than before.
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
        # Slim the provenance trace the same way. The card only renders a count of grounded
        # spans plus the flagged ones (short quote + source link) — the full text and the
        # per-span notes of every grounded span are downloaded and never shown. Single-draft
        # responses (refine, verify-claims) still return the complete trace.
        for d in p.drafts:
            segs = d.provenance if isinstance(d.provenance, list) else []
            d.provenance = [
                {"level": s.get("level"),
                 "text": (s.get("text") or "")[:70],
                 "source_url": s.get("source_url", "")}
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


@router.get("/apify-usage")
def apify_usage():
    """Per-account Apify spend vs monthly credit, for the expense tracker."""
    return account_usage()


def _draft_context(db: Session, post: Post):
    """Shared anti-repetition context for BOTH drafting and refining, so a Tweak gets the same
    guardrail inputs as a fresh Draft: (recent) this client's recent drafts to avoid; (global) a
    cross-client sample for the self-aware profile; (approved) the client's approved comments
    (voice/learning); (siblings) comments OTHER profiles already made on this SAME post."""
    recent = [
        r[0] for r in db.query(Draft.text)
        .join(Post, Post.id == Draft.post_id)
        .filter(Post.client_id == post.client_id, Draft.post_id != post.id)
        .order_by(Draft.created_at.desc()).limit(20).all()
    ]
    global_recent = [
        r[0] for r in db.query(Draft.text)
        .filter(Draft.post_id != post.id)
        .order_by(Draft.created_at.desc()).limit(40).all()
    ]
    approved = [
        (d.edited_text or d.text) for d in db.query(Draft)
        .join(Post, Post.id == Draft.post_id)
        .filter(Post.client_id == post.client_id, Draft.status.in_(["approved", "posted"]))
        .order_by(Draft.created_at.desc()).limit(8).all()
    ]
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
        and round(post.relevance_score * 10) < MIN_DRAFT_RELEVANCE
    ):
        raise HTTPException(
            422,
            f"This post scored {round(post.relevance_score * 10)}/10 for {post.client.name} — below the "
            f"{MIN_DRAFT_RELEVANCE}/10 bar, so a comment would be polite noise rather than value. "
            "Skip it, or raise its relevance if the score looks wrong.",
        )

    recent, global_recent, approved, siblings = _draft_context(db, post)

    # Two DIVERSE candidates so the reviewer picks the angle they like (acting on one
    # auto-discards the other — see update_draft).
    texts = generate_drafts(post.client, post, count=2, avoid_texts=recent, voice_examples=approved,
                            global_texts=global_recent, sibling_texts=siblings)
    if not texts:
        raise HTTPException(502, "draft generation failed — try again")

    # Replace any existing non-posted drafts so regenerating never stacks up copies.
    for d in list(post.drafts):
        if d.status != "posted":
            db.delete(d)
    db.flush()

    docs_text = _docs_text(db, post.client_id)
    client = post.client
    # Force-load the attributes the safety pass reads, so the worker threads below never trigger a
    # lazy DB load off the session (SQLAlchemy sessions are not thread-safe).
    _ = (client.name, client.voice_samples, client.viewpoints, client.key_messages,
         client.guardrails, post.content_snippet)

    def _safe(text: str):
        """Provenance + the 'nothing to fact-check' enforcement for ONE candidate. No DB access."""
        provenance = annotate_provenance(client, post, text, docs_text)
        flagged = _flagged_claims(provenance)
        if flagged:
            safer = strip_unverifiable(client, post, text, flagged)
            if safer and safer != text:
                text = safer
                provenance = annotate_provenance(client, post, text, docs_text)
        return text, provenance

    # Run the candidates' safety passes CONCURRENTLY: serially they made a two-candidate draft
    # ~60s (the serverless ceiling); in parallel the cost is the slowest one, not the sum.
    try:
        with ThreadPoolExecutor(max_workers=min(len(texts), 3)) as ex:
            results = list(ex.map(_safe, texts))
    except Exception:
        results = [_safe(t) for t in texts]

    created = []
    for i, (text, provenance) in enumerate(results):
        draft = Draft(post_id=post.id, variant_index=i, text=text, provenance=provenance)
        db.add(draft)
        created.append(draft)
    db.commit()
    for d in created:
        db.refresh(d)
    return created


@router.post("/drafts/{draft_id}/refine", response_model=DraftOut)
def refine_draft_route(draft_id: int, payload: RefineDraftRequest, db: Session = Depends(get_db)):
    """Rewrite a draft per an operator instruction (e.g. 'make it shorter', 'more
    personal', 'add a question'), keeping it in the client's voice."""
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")
    post = db.get(Post, draft.post_id)
    current = draft.edited_text or draft.text
    # Same anti-repetition context as a fresh draft, so a Tweak is fully guarded too (no more
    # 'Curious'/praise-slop leaking back in through the refine path).
    recent, global_recent, approved, siblings = _draft_context(db, post)
    revised = refine_draft(post.client, post, current, payload.instruction, avoid_texts=recent,
                           voice_examples=approved, global_texts=global_recent, sibling_texts=siblings)
    docs_text = _docs_text(db, post.client_id)
    provenance = annotate_provenance(post.client, post, revised, docs_text)
    # Enforce "nothing to fact-check" on the TWEAK path too. A tweak (especially "more scientific"
    # / "more authoritative") is a prime way for an unverifiable claim to come back, and previously
    # this route only re-labelled it and handed it to the reviewer.
    flagged = _flagged_claims(provenance)
    if flagged:
        safer = strip_unverifiable(post.client, post, revised, flagged)
        if safer and safer != revised:
            revised = safer
            provenance = annotate_provenance(post.client, post, revised, docs_text)
    draft.text = revised
    draft.edited_text = None  # revised text supersedes prior manual edits
    draft.provenance = provenance
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
    flagged_segs = [s for s in segments if s.get("level") == "unverified"][:2]
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


@router.patch("/drafts/{draft_id}", response_model=None)
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
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
                db.delete(sib)

    db.commit()
    return {"ok": True}
