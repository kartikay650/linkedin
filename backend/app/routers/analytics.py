"""Lightweight engagement analytics — who we're replying to most, and how much
is moving through the pipeline per client."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client, Draft, Post, client_active

router = APIRouter(tags=["analytics"])


@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    # Clients being served now. An archived client is left out of every number here, as on the
    # sidebar. Nothing here changes their rows, so unarchiving brings back whatever wasn't removed
    # or dismissed at archive time (see client_active).
    live = client_active(Post.client_id)
    drafts = db.query(Draft).join(Post, Draft.post_id == Post.id).filter(live)
    totals = {
        "clients": db.query(Client).filter(client_active(Client.id)).count(),
        "posts": db.query(Post).filter(Post.dismissed.is_(False), live).count(),
        "drafts": drafts.count(),
        "approved": drafts.filter(Draft.status == "approved").count(),
        "posted": drafts.filter(Draft.status == "posted").count(),
    }

    # Whose posts are we engaging with the most (a draft approved or posted).
    rows = (
        db.query(Post.author_name, func.count(Draft.id))
        .join(Draft, Draft.post_id == Post.id)
        .filter(Draft.status.in_(["approved", "posted"]), live)
        .group_by(Post.author_name)
        .order_by(func.count(Draft.id).desc())
        .limit(10)
        .all()
    )
    top_authors = [{"author": (a or "Unknown"), "replies": int(n)} for a, n in rows]

    per_client = []
    for c in db.query(Client).filter(client_active(Client.id)).order_by(Client.name).all():
        base = db.query(Draft).join(Post, Draft.post_id == Post.id).filter(Post.client_id == c.id)
        per_client.append({
            "client": c.name,
            "posts": db.query(Post).filter(Post.client_id == c.id, Post.dismissed.is_(False)).count(),
            "pending": base.filter(Draft.status == "pending").count(),
            "approved": base.filter(Draft.status == "approved").count(),
            "posted": base.filter(Draft.status == "posted").count(),
        })

    return {"totals": totals, "top_authors": top_authors, "per_client": per_client}
