"""Deduped, batched sync. The dashboard drives it in two steps so a single request
never risks Vercel's 60s ceiling:

  POST /sync/plan  -> the de-duplicated work-list of profiles due for a fetch
  POST /sync/fire  -> fire a batch of them (time-bounded); repeat until done

Each profile is fetched ONCE; the webhook fans its posts out to every client that
tracks it. Universal (no client_id) syncs the whole agency; client_id scopes it.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.jobs.discovery import backfill_client, fire_profiles, plan_profiles
from app.models import Client

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncPlanRequest(BaseModel):
    client_id: Optional[int] = None


class ProfileItem(BaseModel):
    url: str
    label: str = ""
    posts: int = 1


class SyncFireRequest(BaseModel):
    profiles: list[ProfileItem]


@router.post("/plan")
def sync_plan(payload: SyncPlanRequest, db: Session = Depends(get_db)):
    """Return the unique profiles due for a fetch (deduped across clients). The
    frontend fires them in small batches via /sync/fire and shows progress."""
    client = db.get(Client, payload.client_id) if payload.client_id else None
    profiles = plan_profiles(db, client)
    return {"profiles": profiles, "total": len(profiles)}


@router.post("/backfill")
def sync_backfill(payload: SyncPlanRequest, db: Session = Depends(get_db)):
    """One-time/maintenance: give a client (or every client) the recent posts we already
    have for their assigned profiles — no re-scrape. Fixes clients assigned to creators
    that were fetched before the assignment. Time-bounded; idempotent (re-runnable)."""
    clients = [db.get(Client, payload.client_id)] if payload.client_id else db.query(Client).all()
    total_added = 0
    for client in clients:
        if not client:
            continue
        added, _ = backfill_client(db, client)
        total_added += added
    return {"ok": True, "posts_added": total_added, "clients": len([c for c in clients if c])}


@router.post("/fire")
def sync_fire(payload: SyncFireRequest, db: Session = Depends(get_db)):
    """Fire this batch of profiles (fan-out webhook, cadence stamped). Time-bounded:
    returns any it couldn't reach within the budget so the caller retries them."""
    profiles = [p.model_dump() for p in payload.profiles]
    attempted, remaining = fire_profiles(db, profiles)
    return {"fired": attempted, "remaining": remaining, "done": len(remaining) == 0}
