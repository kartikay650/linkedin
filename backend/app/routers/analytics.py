"""Lightweight engagement analytics — who we're replying to most, and how much
is moving through the pipeline per client."""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Client, Draft, Post

router = APIRouter(tags=["analytics"])


@router.get("/analytics")
def analytics(db: Session = Depends(get_db)):
    totals = {
        "clients": db.query(Client).count(),
        "posts": db.query(Post).filter(Post.dismissed.is_(False)).count(),
        "drafts": db.query(Draft).count(),
        "approved": db.query(Draft).filter(Draft.status == "approved").count(),
        "posted": db.query(Draft).filter(Draft.status == "posted").count(),
    }

    # Whose posts are we engaging with the most (a draft approved or posted).
    rows = (
        db.query(Post.author_name, func.count(Draft.id))
        .join(Draft, Draft.post_id == Post.id)
        .filter(Draft.status.in_(["approved", "posted"]))
        .group_by(Post.author_name)
        .order_by(func.count(Draft.id).desc())
        .limit(10)
        .all()
    )
    top_authors = [{"author": (a or "Unknown"), "replies": int(n)} for a, n in rows]

    per_client = []
    for c in db.query(Client).order_by(Client.name).all():
        base = db.query(Draft).join(Post, Draft.post_id == Post.id).filter(Post.client_id == c.id)
        per_client.append({
            "client": c.name,
            "posts": db.query(Post).filter(Post.client_id == c.id, Post.dismissed.is_(False)).count(),
            "pending": base.filter(Draft.status == "pending").count(),
            "approved": base.filter(Draft.status == "approved").count(),
            "posted": base.filter(Draft.status == "posted").count(),
        })

    return {"totals": totals, "top_authors": top_authors, "per_client": per_client}
