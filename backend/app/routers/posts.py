from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.llm.draft import generate_drafts, refine_draft
from app.llm.provenance import annotate_provenance, verify_claims
from app.models import Client, ClientDocument, Draft, Post
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
    db: Session = Depends(get_db),
):
    query = (
        db.query(Post)
        .options(joinedload(Post.drafts))
        .filter(Post.client_id == client_id, Post.dismissed.is_(False))
        .order_by(Post.relevance_score.desc().nullslast(), Post.fetched_at.desc())
    )
    posts = query.all()

    def has(post, status):
        return any(d.status == status for d in post.drafts)

    if view == "posted":
        posts = [p for p in posts if has(p, "posted")]
    elif view == "approved":
        # Scientist-approved and waiting to be posted (not yet live).
        posts = [p for p in posts if has(p, "approved") and not has(p, "posted")]
    elif view == "needs_review":
        # Nothing approved or posted yet — still needs a human to work it.
        posts = [p for p in posts if not has(p, "approved") and not has(p, "posted")]
    elif view == "all":
        pass
    else:  # "active" — the working queue: hide anything already posted/live
        posts = [p for p in posts if not has(p, "posted")]
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
    flagged = [s["text"] for s in segments if s.get("level") == "unverified"]
    if not flagged:
        return draft

    results = verify_claims(draft.edited_text or draft.text, flagged)
    # Fold each verdict back onto its matching segment.
    by_claim = {r.get("claim", ""): r for r in results}
    for seg in segments:
        if seg.get("level") != "unverified":
            continue
        r = by_claim.get(seg["text"]) or next((x for x in results if seg["text"] in x.get("claim", "") or x.get("claim", "") in seg["text"]), None)
        if not r:
            continue
        verdict = r.get("verdict")
        seg["source_url"] = r.get("source_url", "")
        seg["note"] = r.get("note", seg.get("note", ""))
        if verdict == "supported":
            seg["level"] = "grounded"
        elif verdict == "contradicted":
            seg["level"] = "contradicted"
        # "unconfirmed" stays "unverified"

    draft.provenance = segments
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
