"""Apify self-test — verify the token, actor id, input mapping, and output
normalisation against a real profile BEFORE wiring Apify into sync.

Prints the raw actor output (so you can confirm which fields carry the post URL,
text, author, engagement) and then what our normaliser extracted from it. If the
normalised posts look empty but the raw output has data, adjust the field names
in apify_client._normalise (or apify_input_json in .env).

Usage:
    docker compose exec backend python -m app.scraper.check_apify \
        --profile https://www.linkedin.com/in/peterattiamd/
"""
import argparse
import json
import sys

from app.config import settings
from app.scraper.apify_client import _build_input, _normalise, run_actor_raw, ApifyError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()

    if not settings.apify_token:
        print("APIFY_TOKEN not set in .env — nothing to test yet.")
        sys.exit(1)

    try:
        payload = _build_input(args.profile, args.limit)
    except ApifyError as e:
        print(f"input template problem: {e}")
        sys.exit(1)

    print(f"actor: {settings.apify_actor_id}")
    print(f"input: {json.dumps(payload)}")
    print("running (can take 30s–2min)...\n")

    try:
        items = run_actor_raw(args.profile, args.limit)
    except ApifyError as e:
        print(f"✗ {e}")
        print("  → check token, actor id, and that apify_input_json matches this actor's schema.")
        sys.exit(1)

    print(f"✓ actor returned {len(items)} raw item(s)")
    if items:
        print("\n--- RAW item[0] (field names to map) ---")
        print(json.dumps(items[0], indent=2)[:2500])

    normalised = [p for p in (_normalise(it) for it in items) if p]
    print(f"\n--- NORMALISED {len(normalised)} post(s) ---")
    for p in normalised[:args.limit]:
        print(f"  url:    {p['post_url']}")
        print(f"  author: {p['author_name']!r}")
        print(f"  text:   {p['content_snippet'][:120]!r}")
        print(f"  engag:  {p['engagement']}")
        print()

    if items and not normalised:
        print("⚠ raw data came back but nothing normalised — the field names differ.")
        print("  Update the key lists in apify_client._normalise to match the RAW item above.")
    elif normalised:
        print("✓ mapping works. Set POSTS_PROVIDER=apify in .env to use it for sync.")


if __name__ == "__main__":
    main()
