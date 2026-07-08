from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.jobs.discovery import run_discovery_for_client
from app.models import Client, WatchCreator
from app.schemas import ClientCreate, ClientOut, WatchCreatorCreate, WatchCreatorOut

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
def list_clients(db: Session = Depends(get_db)):
    return db.query(Client).all()


@router.post("", response_model=ClientOut)
def create_client(payload: ClientCreate, db: Session = Depends(get_db)):
    client = Client(**payload.model_dump())
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: int, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")
    return client


@router.get("/{client_id}/watch-creators", response_model=list[WatchCreatorOut])
def list_watch_creators(client_id: int, db: Session = Depends(get_db)):
    return db.query(WatchCreator).filter(WatchCreator.client_id == client_id).all()


@router.post("/{client_id}/watch-creators", response_model=WatchCreatorOut)
def add_watch_creator(client_id: int, payload: WatchCreatorCreate, db: Session = Depends(get_db)):
    if not db.get(Client, client_id):
        raise HTTPException(404, "client not found")

    creator = WatchCreator(client_id=client_id, **payload.model_dump())
    db.add(creator)
    db.commit()
    db.refresh(creator)
    return creator


@router.delete("/{client_id}/watch-creators/{creator_id}")
def remove_watch_creator(client_id: int, creator_id: int, db: Session = Depends(get_db)):
    creator = db.get(WatchCreator, creator_id)
    if not creator or creator.client_id != client_id:
        raise HTTPException(404, "watch creator not found")
    db.delete(creator)
    db.commit()
    return {"ok": True}


@router.post("/{client_id}/sync")
def sync_client(client_id: int, db: Session = Depends(get_db)):
    """Manually trigger discovery for this client right now. Runs synchronously —
    deliberately paced (rate-limited delays between each watch-creator), so this
    can take a few minutes for clients with several creators. That pacing is a
    safety feature, not a bug."""
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "client not found")

    try:
        new_posts = run_discovery_for_client(db, client)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"sync failed: {e}")

    return {"new_posts": new_posts}
