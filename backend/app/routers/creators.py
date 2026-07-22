"""The shared, agency-wide creator database (Lara's ICP list). kind='creator'
profiles are tracked and commented on; kind='prospect' are lead-gen targets
surfaced in the Prospects tab. The operator can add their own or promote a
prospect to a tracked creator — we deliberately do NOT auto-discover new profiles.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.jobs.discovery import backfill_client_creator
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
    if "linkedin.com/in/" not in url.lower():
        raise HTTPException(400, "That doesn't look like a LinkedIn profile. The link should contain 'linkedin.com/in/…' (a personal profile, not a company page or a search link).")
    url = url.split("?")[0].rstrip("/") + "/"  # normalise for dedup
    existing = db.query(Creator).filter(Creator.profile_url == url).first()
    if existing:
        return existing
    freq = payload.post_frequency if payload.post_frequency in ("yes", "sometimes", "no") else "sometimes"
    creator = Creator(
        name=(payload.name or "").strip(),
        profile_url=url,
        headline=payload.headline or "",
        kind=payload.kind if payload.kind in ("creator", "prospect") else "creator",
        active=True,
        post_frequency=freq,
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
    if payload.post_frequency in ("yes", "sometimes", "no"):
        creator.post_frequency = payload.post_frequency
    db.commit()
    db.refresh(creator)
    return creator


@router.put("/{creator_id}/clients", response_model=CreatorOut)
def set_creator_clients(creator_id: int, payload: CreatorClientsUpdate, db: Session = Depends(get_db)):
    """Set exactly which clients this creator is assigned to. The creator's posts are
    only pulled for these clients (see discovery.plan_profiles)."""
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
    newly_added = [cid for cid in wanted if cid not in existing]
    for cid in newly_added:
        db.add(CreatorClient(creator_id=creator_id, client_id=cid))
    db.commit()
    # Backfill each newly-assigned client with this profile's recent posts we already have.
    for cid in newly_added:
        client = db.get(Client, cid)
        if client:
            backfill_client_creator(db, client, creator.profile_url)
    db.refresh(creator)
    return creator


@router.put("/{creator_id}/clients/{client_id}")
def assign_creator_client(creator_id: int, client_id: int, db: Session = Depends(get_db)):
    """Idempotently assign ONE client to a creator. A single-row op, so ticking several
    clients quickly can't overwrite each other the way the full-set PUT could."""
    if not db.get(Creator, creator_id):
        raise HTTPException(404, "creator not found")
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")
    exists = (
        db.query(CreatorClient)
        .filter(CreatorClient.creator_id == creator_id, CreatorClient.client_id == client_id)
        .first()
    )
    if not exists:
        db.add(CreatorClient(creator_id=creator_id, client_id=client_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # a concurrent tick already created it — that's fine
    # Immediately give this client the profile's recent posts we already have (no re-scrape),
    # so a freshly-assigned creator isn't invisible until its next cadence window.
    creator = db.get(Creator, creator_id)
    client = db.get(Client, client_id)
    added = backfill_client_creator(db, client, creator.profile_url) if creator and client else 0
    return {"ok": True, "creator_id": creator_id, "client_id": client_id, "assigned": True, "backfilled": added}


@router.delete("/{creator_id}/clients/{client_id}")
def unassign_creator_client(creator_id: int, client_id: int, db: Session = Depends(get_db)):
    """Idempotently unassign ONE client from a creator."""
    db.query(CreatorClient).filter(
        CreatorClient.creator_id == creator_id, CreatorClient.client_id == client_id
    ).delete()
    db.commit()
    return {"ok": True, "creator_id": creator_id, "client_id": client_id, "assigned": False}


@router.delete("/{creator_id}")
def delete_creator(creator_id: int, db: Session = Depends(get_db)):
    creator = db.get(Creator, creator_id)
    if creator:
        db.delete(creator)
        db.commit()
    return {"ok": True}
