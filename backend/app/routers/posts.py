from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_db
from app.llm.draft import generate_drafts, refine_draft
from app.llm.provenance import annotate_provenance, verify_claims
from app.models import Client, ClientDocument, Draft, Post
from app.profiles import excluded_author_slugs, profile_slug
from app.scraper.apify_client import account_usage
from app.schemas import DraftOut, DraftUpdate, PostWithDrafts, RefineDraftRequest

router = APIRouter(tags=["posts"])


def _docs_text(db: Session, client_id: int) -> str:
    """Concatenated extracted text of the client's processed documents, used to
    ground the clinical-safety provenance check."""
    docs = (
        db.query(ClientDocument)
        .filter(ClientDocument.client_id == client_id, ClientDocument.status == "done")
        .all()
    )
    return "\n\n".join((d.extracted_text or "") for d in docs)


def _visible_posts(db: Session, client_id: int, max_age_days: int) -> list[Post]:
    """The client's base feed BEFORE the per-tab filter: not dismissed, fresh enough (or
    carrying in-progress work), with the client's own and same-company colleagues' posts
    removed. Shared source of truth for both the post list and the per-tab counts, so the
    tab badges can never disagree with what a tab actually shows."""
    posts = (
        db.query(Post)
        .options(joinedload(Post.drafts))
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

    # Drop 0/10-relevance posts from EVERY view — they only clutter the queue. Keep a post if
    # it's unscored (scoring may still be pending) or already has in-progress work. These are
    # filtered, not deleted, so the threshold can be relaxed later if the scorer ever zeroes a
    # genuinely good post.
    def too_irrelevant(post):
        s = post.relevance_score
        return s is not None and round(s * 10) < 1 and not has_working_draft(post)

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


@router.get("/clients/{client_id}/posts", response_model=list[PostWithDrafts])
def list_posts_for_client(
    client_id: int,
    view: str = Query("active", description="active | needs_review | approved | posted | all"),
    max_age_days: int = Query(14, description="only show posts newer than this many days"),
    db: Session = Depends(get_db),
):
    return [p for p in _visible_posts(db, client_id, max_age_days) if _in_view(p, view)]


@router.get("/clients/{client_id}/post-counts")
def post_counts(
    client_id: int,
    max_age_days: int = Query(14, description="same window as the post list"),
    db: Session = Depends(get_db),
):
    """Per-tab counts for the badge on each tab (Queue/Draft/Approved/Posted/All). Computed
    from the exact same visible set as the list, so the numbers always match the tabs."""
    posts = _visible_posts(db, client_id, max_age_days)
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
        posts = _visible_posts(db, client.id, max_age_days)
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


@router.post("/posts/{post_id}/draft", response_model=list[DraftOut])
def draft_reply(post_id: int, db: Session = Depends(get_db)):
    """Generate reply drafts for a post — only ever called explicitly by a human
    clicking 'Draft reply', never automatically during discovery."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post not found")

    # The client's recent drafts (across their other posts) — passed so the generator
    # writes something structurally different and doesn't converge on one template.
    recent = [
        r[0] for r in db.query(Draft.text)
        .join(Post, Post.id == Draft.post_id)
        .filter(Post.client_id == post.client_id, Draft.post_id != post.id)
        .order_by(Draft.created_at.desc())
        .limit(20).all()
    ]
    # A GLOBAL sample of the tool's recent output across ALL clients — so `output_profile`
    # can catch a pattern that spreads across clients (e.g. the "Curious ...?" question tic),
    # which a per-client-only view misses. See generate_drafts' self-aware anti-repetition.
    global_recent = [
        r[0] for r in db.query(Draft.text)
        .filter(Draft.post_id != post.id)
        .order_by(Draft.created_at.desc())
        .limit(40).all()
    ]
    # Learning loop: comments the team already approved/posted for this client are the
    # gold standard for their real voice — feed them in so drafts sound less "AI" over
    # time, with no manual example-seeding. (Final text = the human-edited version.)
    approved = [
        (d.edited_text or d.text) for d in db.query(Draft)
        .join(Post, Post.id == Draft.post_id)
        .filter(Post.client_id == post.client_id, Draft.status.in_(["approved", "posted"]))
        .order_by(Draft.created_at.desc())
        .limit(8).all()
    ]
    # Comments OTHER profiles already made on this SAME post (posts share a URL across clients).
    # Passed so this client takes a genuinely different, self-tailored angle instead of echoing
    # another profile — the fix for "two profiles get near-identical comments on the same post".
    siblings = []
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
    created = []
    for i, text in enumerate(texts):
        provenance = annotate_provenance(post.client, post, text, docs_text)
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
    revised = refine_draft(post.client, post, current, payload.instruction)
    draft.text = revised
    draft.edited_text = None  # revised text supersedes prior manual edits
    draft.provenance = annotate_provenance(post.client, post, revised, _docs_text(db, post.client_id))
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
