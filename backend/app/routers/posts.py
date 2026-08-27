from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session, joinedload, load_only, selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.llm.draft import generate_drafts, refine_draft, strip_unverifiable
from app.llm.provenance import CHECK_FAILED_NOTE, annotate_provenance, verify_claims
from app.models import Client, ClientDocument, Draft, Post
from app.profiles import excluded_author_slugs, profile_slug
from app.scraper.apify_client import account_usage
from app.schemas import DraftOut, DraftUpdate, PostWithDrafts, RefineDraftRequest

router = APIRouter(tags=["posts"])

# Relevance floor (out of 10). Posts scoring below this are hidden from the feed and refused by the
# draft route: the scorer reliably marks them as posts the client can add nothing to, and commenting
# there reads as polite noise. The scorer's own distribution has a natural gap at 4-6, so 4 is a
# clean cut. Unscored posts and posts already carrying work are always kept.
MIN_DRAFT_RELEVANCE = 4


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


def _visible_posts(db: Session, client_id: int, max_age_days: int, light: bool = False) -> list[Post]:
    """The client's base feed BEFORE the per-tab filter: not dismissed, fresh enough (or
    carrying in-progress work), with the client's own and same-company colleagues' posts
    removed. Shared source of truth for both the post list and the per-tab counts, so the
    tab badges can never disagree with what a tab actually shows.

    `light=True` fetches ONLY the columns the filtering/counting logic actually touches
    (timestamps, relevance, author, dismissed, and each draft's status/created_at) and NOT the
    heavy fields (content_snippet, draft text/edited_text, provenance JSON). Same rows, same
    logic, a fraction of the bytes — used by the count badges and the notification summary so
    they stop reading megabytes just to produce a few numbers (the main egress fix)."""
    if light:
        query = (
            db.query(Post)
            .options(
                load_only(Post.id, Post.client_id, Post.posted_at, Post.fetched_at,
                          Post.relevance_score, Post.dismissed, Post.author_profile_url, Post.source_ref),
                joinedload(Post.drafts).load_only(Draft.status, Draft.created_at),
            )
        )
    else:
        query = db.query(Post).options(joinedload(Post.drafts))
    posts = (
        query
        .filter(Post.client_id == client_id, Post.dismissed.is_(False))
        .order_by(Post.relevance_score.desc().nullslast(), Post.fetched_at.desc())
        .all()
    )

    # Only surface fresh posts — engaging early is the whole point. Fall back to
    # fetch time when a post has no publish date (it was just scraped).
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    def recent(post):
        dt = post.posted_at or post.fetched_at
        if dt is None:
            return True
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= cutoff

    # A post with in-progress work (a drafted/approved reply, or a generated one still
    # in the Queue) must NEVER be hidden by recency — otherwise queued drafts vanish once
    # the underlying post ages past the window. Recency only prunes the undrafted Queue.
    def has_working_draft(post):
        return any(d.status in ("pending", "drafted", "approved") for d in post.drafts)

    posts = [p for p in posts if recent(p) or has_working_draft(p)]

    # Hide the client's own posts and same-company colleagues' posts (safety net that
    # also covers anything fetched before this rule existed). See app/profiles.py.
    client = db.get(Client, client_id)
    if client:
        excluded = excluded_author_slugs(db, client)
        if excluded:
            posts = [
                p for p in posts
                if (profile_slug(p.author_profile_url) or profile_slug(p.source_ref)) not in excluded
            ]

    # Drop low-relevance posts from EVERY view — they only clutter the queue, and drafting on them
    # produced the comments the reviewer called "not worth my time". Keep a post if it's unscored
    # (scoring may still be pending) or already has in-progress work. Filtered, not deleted, so the
    # threshold can be relaxed if the scorer ever under-rates a genuinely good post.
    def too_irrelevant(post):
        s = post.relevance_score
        return s is not None and round(s * 10) < MIN_DRAFT_RELEVANCE and not has_working_draft(post)

    posts = [p for p in posts if not too_irrelevant(p)]

    # Order: newest DAY first, then most-relevant WITHIN each day (ties -> newest time). This
    # surfaces fresh posts without discarding relevance — a barely-relevant newer post no longer
    # buries a highly-relevant one from the same day. Recency uses the post's publish date
    # (posted_at), falling back to fetch time only when there's no publish date.
    def _order_key(post):
        dt = post.posted_at or post.fetched_at
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt.date() if dt else date.min, post.relevance_score or 0.0,
                dt or datetime.min.replace(tzinfo=timezone.utc))

    posts.sort(key=_order_key, reverse=True)
    return posts


def _has(post, status) -> bool:
    return any(d.status == status for d in post.drafts)


def _in_view(post, view: str) -> bool:
    """Whether a post belongs in a given tab. active/draft/approved/posted partition the
    feed (each post lands in exactly one); "all" is everything; "needs_review" is a legacy alias."""
    if view == "posted":
        return _has(post, "posted")
    if view == "approved":  # scientist-approved, waiting to be posted (not yet live)
        return _has(post, "approved") and not _has(post, "posted")
    if view == "draft":  # explicitly moved to Draft (status "drafted"), not yet approved/posted
        return _has(post, "drafted") and not _has(post, "approved") and not _has(post, "posted")
    if view == "needs_review":  # legacy alias
        return not _has(post, "approved") and not _has(post, "posted")
    if view == "all":
        return True
    # "active" — the Queue: not moved to draft/approved/posted (a generated "pending" reply stays here)
    return not _has(post, "drafted") and not _has(post, "approved") and not _has(post, "posted")


def _paged_posts(db: Session, client_id: int, view: str, max_age_days: int,
                 limit: int, offset: int) -> list[Post]:
    """Egress-lean feed read: apply recency + relevance + the requested VIEW filter in SQL and
    paginate, so the backend fetches only the page actually shown instead of the client's entire
    post set (the old path pulled all ~900 rows on every load/tab-switch — the main egress hog).
    Drafts for the page load via selectinload (one extra IN query — pagination-safe). The count
    badges keep using the all-rows light path in _visible_posts, so they stay correct and cheap."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=max_age_days)
    dt = func.coalesce(Post.posted_at, Post.fetched_at)
    working = exists().where(and_(Draft.post_id == Post.id, Draft.status.in_(("pending", "drafted", "approved"))))
    drafted = exists().where(and_(Draft.post_id == Post.id, Draft.status == "drafted"))
    approved = exists().where(and_(Draft.post_id == Post.id, Draft.status == "approved"))
    posted = exists().where(and_(Draft.post_id == Post.id, Draft.status == "posted"))

    q = (
        db.query(Post)
        .filter(Post.client_id == client_id, Post.dismissed.is_(False))
        # fresh enough, OR carrying in-progress work (never hide queued/drafted work by age)
        .filter(or_(dt >= cutoff, working))
        # drop 0/10-relevance unless unscored or already being worked
        .filter(or_(Post.relevance_score.is_(None),
                    func.round(Post.relevance_score * 10) >= MIN_DRAFT_RELEVANCE, working))
    )
    if view == "posted":
        q = q.filter(posted)
    elif view == "approved":
        q = q.filter(and_(approved, ~posted))
    elif view == "draft":
        q = q.filter(and_(drafted, ~approved, ~posted))
    elif view == "needs_review":
        q = q.filter(and_(~approved, ~posted))
    elif view != "all":  # "active" (the Queue) — the default
        q = q.filter(and_(~drafted, ~approved, ~posted))

    # newest DAY first, then most-relevant within the day, then newest time (matches _order_key)
    posts = (
        q.order_by(func.date(dt).desc(), Post.relevance_score.desc().nullslast(), dt.desc())
        .options(selectinload(Post.drafts))
        .offset(max(0, offset))
        .limit(max(1, min(limit, 200)))
        .all()
    )

    # Hide the client's own / same-company posts (few; slug logic isn't SQL-friendly, so post-filter).
    client = db.get(Client, client_id)
    if client:
        excluded = excluded_author_slugs(db, client)
        if excluded:
            posts = [
                p for p in posts
                if (profile_slug(p.author_profile_url) or profile_slug(p.source_ref)) not in excluded
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
    """Per-tab counts for the badge on each tab (Queue/Draft/Approved/Posted/All). Computed
    from the exact same visible set as the list, so the numbers always match the tabs."""
    posts = _visible_posts(db, client_id, max_age_days, light=True)
    return {
        "active": sum(1 for p in posts if _in_view(p, "active")),
        "draft": sum(1 for p in posts if _in_view(p, "draft")),
        "approved": sum(1 for p in posts if _in_view(p, "approved")),
        "posted": sum(1 for p in posts if _in_view(p, "posted")),
        "all": len(posts),
    }


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
    it's been sitting — there's no status-change timestamp)."""
    now = datetime.now(timezone.utc)
    # stage key -> (tab view for _in_view, the draft status whose age we measure)
    STAGE = {"to_post": ("approved", "approved"), "to_approve": ("draft", "drafted")}

    def oldest_hours(items, status):
        oldest = None
        for p in items:
            for d in p.drafts:
                if d.status == status and d.created_at:
                    ts = d.created_at if d.created_at.tzinfo else d.created_at.replace(tzinfo=timezone.utc)
                    if oldest is None or ts < oldest:
                        oldest = ts
        return round((now - oldest).total_seconds() / 3600, 1) if oldest else None

    result = {k: {"total": 0, "oldest_hours": None, "by_client": []} for k in STAGE}
    for client in db.query(Client).order_by(Client.name).all():
        posts = _visible_posts(db, client.id, max_age_days, light=True)
        for key, (view, status) in STAGE.items():
            items = [p for p in posts if _in_view(p, view)]
            if not items:
                continue
            oh = oldest_hours(items, status)
            result[key]["total"] += len(items)
            result[key]["by_client"].append(
                {"id": client.id, "name": client.name, "count": len(items), "oldest_hours": oh}
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
