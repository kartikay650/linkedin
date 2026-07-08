import random
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Burner, BurnerEvent, BurnerStatus


class DailyCapReached(Exception):
    pass


def _reset_if_new_day(db: Session, burner: Burner) -> None:
    now = datetime.utcnow()
    if burner.actions_reset_at is None or burner.actions_reset_at.date() < now.date():
        burner.actions_today = 0
        burner.actions_reset_at = now
        db.commit()


def check_and_reserve_action(db: Session, burner: Burner) -> None:
    """Raises DailyCapReached if the burner is out of budget for today.
    Call this immediately before every scrape action; on success it increments the counter."""
    if burner.status != BurnerStatus.active:
        raise DailyCapReached(f"burner {burner.id} is not active ({burner.status})")

    _reset_if_new_day(db, burner)
    if burner.actions_today >= settings.max_actions_per_burner_per_day:
        raise DailyCapReached(f"burner {burner.id} hit its daily action cap")

    burner.actions_today += 1
    db.commit()


def human_delay() -> None:
    """Sleep a randomized, human-like interval. Call this between scrape actions, never skip it."""
    delay = random.uniform(settings.min_delay_seconds, settings.max_delay_seconds)
    time.sleep(delay)


def log_event(db: Session, burner: Burner, event_type: str, detail: str = "") -> None:
    db.add(BurnerEvent(burner_id=burner.id, event_type=event_type, detail=detail))
    db.commit()
