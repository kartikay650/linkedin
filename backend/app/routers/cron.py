"""Scheduled sync. Vercel Cron hits GET /cron/sync-all every morning (see
backend/vercel.json) and sends Authorization: Bearer <CRON_SECRET>. We fire a
sync for every client so fresh threads are waiting each morning — no manual click.

Serverless has a 60s ceiling and firing an actor run per creator is a POST each,
so we work within a time budget: cover as many clients as fit, the rest catch up
on the next run or a manual sync. (A queue would remove the cap; follow-up.)
"""
import time

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.jobs.discovery import start_discovery_for_client
from app.models import Client

router = APIRouter(tags=["cron"])


@router.get("/cron/sync-all")
@router.post("/cron/sync-all")
def cron_sync_all(authorization: str = Header(default=""), db: Session = Depends(get_db)):
    if not settings.cron_secret or authorization != f"Bearer {settings.cron_secret}":
        raise HTTPException(401, "invalid cron secret")

    # Each client's sync now fires the full creator list (~35s). Only start a new
    # client while we're still early enough that one more full client can't push us
    # past the 60s function cap. At 1-2 clients this covers everyone every morning;
    # at many clients it covers as many as fit and the rest catch up next run / on
    # a manual sync (a queue is the unbounded-scale follow-up).
    start = time.monotonic()
    clients_synced = runs_started = 0
    for client in db.query(Client).order_by(Client.id).all():
        if time.monotonic() - start > 20.0:
            break
        try:
            runs_started += start_discovery_for_client(db, client)
            clients_synced += 1
        except Exception as e:  # never let one client abort the whole morning run
            print(f"[cron] sync failed for client {client.id}: {e}")
    return {"ok": True, "clients_synced": clients_synced, "runs_started": runs_started}
