from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from app.db import get_db
from app.llm.draft import generate_drafts, refine_draft
from app.models import Draft, Post
from app.schemas import DraftOut, DraftUpdate, PostWithDrafts, RefineDraftRequest

router = APIRouter(tags=["posts"])


@router.get("/clients/{client_id}/posts", response_model=list[PostWithDrafts])
def list_posts_for_client(
    client_id: int,
    hide_done: bool = Query(True, description="Hide posts that already have a posted reply"),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Post)
        .options(joinedload(Post.drafts))
        .filter(Post.client_id == client_id)
        .order_by(Post.relevance_score.desc().nullslast(), Post.fetched_at.desc())
    )
    posts = query.all()
    if hide_done:
        posts = [p for p in posts if not any(d.status == "posted" for d in p.drafts)]
    return posts


@router.post("/posts/{post_id}/draft", response_model=list[DraftOut])
def draft_reply(post_id: int, db: Session = Depends(get_db)):
    """Generate reply drafts for a post — only ever called explicitly by a human
    clicking 'Draft reply', never automatically during discovery."""
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "post not found")

    texts = generate_drafts(post.client, post, count=2)
    if not texts:
        raise HTTPException(502, "draft generation failed — try again")

    drafts = [Draft(post_id=post.id, variant_index=i, text=text) for i, text in enumerate(texts)]
    db.add_all(drafts)
    db.commit()
    for d in drafts:
        db.refresh(d)
    return drafts


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
