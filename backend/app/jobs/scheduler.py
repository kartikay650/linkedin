"""Long-running scheduler process — runs health checks and discovery on a loop.
Runs as its own container; keep it separate from the API process so a stuck
Playwright job never blocks the dashboard's API requests."""
import time

from app.config import settings
from app.db import SessionLocal
from app.jobs.discovery import run_discovery_for_burner
from app.jobs.health_check import run_health_check
from app.models import Burner

DISCOVERY_INTERVAL_SECONDS = 4 * 60 * 60  # every 4 hours per burner


def main() -> None:
    # Start the clocks at "just ran" rather than "overdue" — otherwise every
    # container restart fires an immediate health check + discovery run against
    # the real burner account before anyone can stop it.
    last_health_check = time.time()
    last_discovery = time.time()

    while True:
        now = time.time()
        db = SessionLocal()
        try:
            if now - last_health_check >= settings.health_check_interval_minutes * 60:
                for burner in db.query(Burner).all():
                    run_health_check(db, burner)
                last_health_check = now

            if now - last_discovery >= DISCOVERY_INTERVAL_SECONDS:
                for burner in db.query(Burner).all():
                    run_discovery_for_burner(db, burner)
                last_discovery = now
        finally:
            db.close()

        time.sleep(60)


if __name__ == "__main__":
    main()
