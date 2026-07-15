"""The shared, agency-wide creator database (Lara's ICP list). kind='creator'
profiles are tracked and commented on; kind='prospect' are lead-gen targets
surfaced in the Prospects tab. The operator can add their own or promote a
prospect to a tracked creator — we deliberately do NOT auto-discover new profiles.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models import Client, Creator, CreatorClient
from app.schemas import CreatorClientsUpdate, CreatorCreate, CreatorOut, CreatorUpdate

router = APIRouter(prefix="/creators", tags=["creators"])


@router.get("", response_model=list[CreatorOut])
def list_creators(kind: Optional[str] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Creator).options(selectinload(Creator.client_links))
    if kind:
        q = q.filter(Creator.kind == kind)
    return q.order_by(Creator.kind, Creator.name).all()


@router.post("", response_model=CreatorOut)
def add_creator(payload: CreatorCreate, db: Session = Depends(get_db)):
    url = (payload.profile_url or "").strip()
    if "linkedin.com/in/" not in url:
        raise HTTPException(400, "a valid LinkedIn profile URL is required")
    url = url.split("?")[0].rstrip("/") + "/"  # normalise for dedup
    existing = db.query(Creator).filter(Creator.profile_url == url).first()
    if existing:
        return existing
    creator = Creator(
        name=(payload.name or "").strip(),
        profile_url=url,
        headline=payload.headline or "",
        kind=payload.kind if payload.kind in ("creator", "prospect") else "creator",
        active=True,
    )
    db.add(creator)
    db.commit()
    db.refresh(creator)
    return creator


@router.patch("/{creator_id}", response_model=CreatorOut)
def update_creator(creator_id: int, payload: CreatorUpdate, db: Session = Depends(get_db)):
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "creator not found")
    if payload.kind in ("creator", "prospect"):
        creator.kind = payload.kind
    if payload.active is not None:
        creator.active = payload.active
    db.commit()
    db.refresh(creator)
    return creator


@router.put("/{creator_id}/clients", response_model=CreatorOut)
def set_creator_clients(creator_id: int, payload: CreatorClientsUpdate, db: Session = Depends(get_db)):
    """Set exactly which clients this creator is assigned to. The creator's posts are
    only pulled for these clients (see discovery._active_creators)."""
    creator = db.get(Creator, creator_id)
    if not creator:
        raise HTTPException(404, "creator not found")

    # Only assign to clients that actually exist; silently drop unknown ids.
    valid_ids = {c.id for c in db.query(Client.id).all()} if payload.client_ids else set()
    wanted = {cid for cid in payload.client_ids if cid in valid_ids}

    existing = {link.client_id: link for link in creator.client_links}
    for cid, link in existing.items():
        if cid not in wanted:
            db.delete(link)
    for cid in wanted:
        if cid not in existing:
            db.add(CreatorClient(creator_id=creator_id, client_id=cid))
    db.commit()
    db.refresh(creator)
    return creator


@router.delete("/{creator_id}")
def delete_creator(creator_id: int, db: Session = Depends(get_db)):
    creator = db.get(Creator, creator_id)
    if creator:
        db.delete(creator)
        db.commit()
    return {"ok": True}
