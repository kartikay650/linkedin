from datetime import datetime, timedelta, timezone

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


@router.get("/clients/{client_id}/posts", response_model=list[PostWithDrafts])
def list_posts_for_client(
    client_id: int,
    view: str = Query("active", description="active | needs_review | approved | posted | all"),
    max_age_days: int = Query(5, description="only show posts newer than this many days"),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Post)
        .options(joinedload(Post.drafts))
        .filter(Post.client_id == client_id, Post.dismissed.is_(False))
        .order_by(Post.relevance_score.desc().nullslast(), Post.fetched_at.desc())
    )
    posts = query.all()

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

    posts = [p for p in posts if recent(p)]

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

    def has(post, status):
        return any(d.status == status for d in post.drafts)

    if view == "posted":
        posts = [p for p in posts if has(p, "posted")]
    elif view == "approved":
        # Scientist-approved and waiting to be posted (not yet live).
        posts = [p for p in posts if has(p, "approved") and not has(p, "posted")]
    elif view == "draft":
        # A reply has been drafted and is awaiting approval (not yet approved/posted).
        posts = [p for p in posts if has(p, "pending") and not has(p, "approved") and not has(p, "posted")]
    elif view == "needs_review":
        # Legacy alias: nothing approved or posted yet.
        posts = [p for p in posts if not has(p, "approved") and not has(p, "posted")]
    elif view == "all":
        pass
    else:  # "active" — the Queue: fresh posts with no working draft yet. Once a reply is
        # drafted it moves to Draft, then Approved, then Posted, so it leaves the Queue.
        posts = [p for p in posts if not has(p, "pending") and not has(p, "approved") and not has(p, "posted")]
    return posts


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

    texts = generate_drafts(post.client, post, count=1)
    if not texts:
        raise HTTPException(502, "draft generation failed — try again")

    # Replace any existing non-posted drafts so regenerating never stacks up copies.
    for d in list(post.drafts):
        if d.status != "posted":
            db.delete(d)
    db.flush()

    provenance = annotate_provenance(post.client, post, texts[0], _docs_text(db, post.client_id))
    draft = Draft(post_id=post.id, variant_index=0, text=texts[0], provenance=provenance)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return [draft]


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


@router.patch("/drafts/{draft_id}", response_model=None)
def update_draft(draft_id: int, payload: DraftUpdate, db: Session = Depends(get_db)):
    draft = db.get(Draft, draft_id)
    if not draft:
        raise HTTPException(404, "draft not found")

    if payload.edited_text is not None:
        draft.edited_text = payload.edited_text
    if payload.status is not None:
        draft.status = payload.status

    db.commit()
    return {"ok": True}
