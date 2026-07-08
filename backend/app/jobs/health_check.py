from datetime import datetime

from sqlalchemy.orm import Session

from app.alerts import send_alert
from app.models import Burner, BurnerStatus, Client
from app.scraper.session import burner_page, CheckpointDetected
from app.scraper.rate_limit import log_event


def run_health_check(db: Session, burner: Burner) -> None:
    try:
        with burner_page(burner) as page:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")

        burner.last_health_ok = True
        burner.status = BurnerStatus.active
        log_event(db, burner, "health_check", "ok")

    except CheckpointDetected as e:
        burner.last_health_ok = False
        burner.status = BurnerStatus.needs_relogin
        log_event(db, burner, "checkpoint", str(e))
        send_alert(f":warning: Burner '{burner.label}' hit a LinkedIn checkpoint and needs manual re-login.")
        redistribute_clients(db, burner)

    except Exception as e:
        burner.last_health_ok = False
        log_event(db, burner, "health_check_failed", str(e))
        send_alert(f":warning: Burner '{burner.label}' health check failed: {e}")

    finally:
        burner.last_health_check_at = datetime.utcnow()
        db.commit()


def redistribute_clients(db: Session, dead_burner: Burner) -> None:
    """Move a down burner's clients onto the remaining active burner(s)."""
    survivors = (
        db.query(Burner)
        .filter(Burner.status == BurnerStatus.active, Burner.id != dead_burner.id)
        .all()
    )
    if not survivors:
        send_alert(
            f":rotating_light: No active burners left after '{dead_burner.label}' went down. "
            f"Fetching is fully stopped until a burner is fixed."
        )
        return

    affected = db.query(Client).filter(Client.burner_id == dead_burner.id).all()
    for i, client in enumerate(affected):
        client.burner_id = survivors[i % len(survivors)].id
    db.commit()
    log_event(db, dead_burner, "redistributed", f"{len(affected)} clients moved to surviving burners")
