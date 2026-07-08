"""Register a burner account in the DB after you've created its session file
with manual_login.py. Run inside the backend container:

    docker compose exec backend python -m app.seed_burner --label burner_1 --session /app/sessions/burner_1.json
"""
import argparse

from app.db import SessionLocal
from app.models import Burner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--session", required=True, help="Path to the storage state JSON, inside the container")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        burner = Burner(label=args.label, storage_state_path=args.session)
        db.add(burner)
        db.commit()
        print(f"Created burner {burner.id} ({burner.label})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
