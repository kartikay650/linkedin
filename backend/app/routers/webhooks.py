"""Apify webhook receiver — called by Apify when a fire-and-forget actor run
finishes (see jobs/discovery.fire_profiles). Fetches the finished run's dataset and
FANS the posts out to every client tracking that profile URL.

This is what makes the deduped model work: a profile is scraped once, and this
callback distributes its posts to all clients that track it (each gets its own
Post row + its own relevance score), so we never scrape the same profile per-client.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.jobs.discovery import _save_and_process
from app.models import Client, Creator, CreatorClient, WatchCreator
from app.scraper.apify_client import _normalise, dataset_items

router = APIRouter(tags=["webhooks"])


def _clients_tracking(db: Session, url: str) -> list[Client]:
    """Every client that tracks this profile URL — as an assigned tracked creator OR
    as a hand-picked watch-creator. Deduped."""
    ids = set()
    rows = (
        db.query(CreatorClient.client_id)
        .join(Creator, Creator.id == CreatorClient.creator_id)
        .filter(Creator.profile_url == url, Creator.kind == "creator", Creator.active.is_(True))
        .all()
    )
    ids.update(r[0] for r in rows)
    ids.update(r[0] for r in db.query(WatchCreator.client_id).filter(WatchCreator.profile_url == url).all())
    if not ids:
        return []
    return db.query(Client).filter(Client.id.in_(ids)).all()


@router.post("/apify/webhook")
async def apify_webhook(request: Request, secret: str = "", db: Session = Depends(get_db)):
    # Verify the shared secret — this endpoint is public, so an unauthenticated
    # caller must not be able to trigger dataset fetches/writes.
    if not settings.apify_webhook_secret or secret != settings.apify_webhook_secret:
        raise HTTPException(401, "invalid webhook secret")

    body = await request.json()
    source_ref = body.get("source_ref") or ""
    label = body.get("creator_label") or ""
    resource = body.get("resource") or {}
    dataset_id = resource.get("defaultDatasetId")

    if not source_ref or not dataset_id:
        return {"ok": False, "reason": "missing source_ref or datasetId"}

    clients = _clients_tracking(db, source_ref)
    if not clients:
        # Fallback for any in-flight run fired before the fan-out change (carried a client_id).
        cid = body.get("client_id")
        c = db.get(Client, cid) if cid else None
        clients = [c] if c else []
    if not clients:
        return {"ok": False, "reason": f"no client tracks {source_ref}"}

    # Fetch the dataset once, then fan the posts out to every tracking client.
    items = [_normalise(it) for it in dataset_items(dataset_id)]
    items = [it for it in items if it]
    saved = 0
    for client in clients:
        for raw in items:
            raw["author_name"] = raw.get("author_name") or label
            _save_and_process(db, client, source_ref, raw)
            saved += 1
    return {"ok": True, "clients": len(clients), "processed": saved}
