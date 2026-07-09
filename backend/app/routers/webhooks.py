"""Apify webhook receiver — called by Apify when a fire-and-forget actor run
finishes (see jobs/discovery.start_discovery_for_client). Fetches the finished
run's dataset and saves the posts for the client/creator encoded in the payload.

This is what makes serverless viable: the original request returned immediately;
this short callback does the saving, so no function is held open while Apify works.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.jobs.discovery import _save_and_process
from app.models import Client
from app.scraper.apify_client import _normalise, dataset_items

router = APIRouter(tags=["webhooks"])


@router.post("/apify/webhook")
async def apify_webhook(request: Request, secret: str = "", db: Session = Depends(get_db)):
    # Verify the shared secret — this endpoint is public, so an unauthenticated
    # caller must not be able to trigger dataset fetches/writes.
    if not settings.apify_webhook_secret or secret != settings.apify_webhook_secret:
        raise HTTPException(401, "invalid webhook secret")

    body = await request.json()
    client_id = body.get("client_id")
    source_ref = body.get("source_ref") or ""
    label = body.get("creator_label") or ""
    resource = body.get("resource") or {}
    dataset_id = resource.get("defaultDatasetId")

    if not client_id or not dataset_id:
        return {"ok": False, "reason": "missing client_id or datasetId"}

    client = db.get(Client, client_id)
    if not client:
        return {"ok": False, "reason": f"client {client_id} no longer exists"}

    saved = 0
    for item in dataset_items(dataset_id):
        raw = _normalise(item)
        if not raw:
            continue
        raw["author_name"] = raw["author_name"] or label
        _save_and_process(db, client, source_ref, raw)
        saved += 1
    return {"ok": True, "processed": saved}
