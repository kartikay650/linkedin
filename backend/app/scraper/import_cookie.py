"""Swap the li_at auth cookie in a burner's session file for one taken from a
real, currently-working browser session (e.g. Safari) — useful when the
Playwright-driven session has been flagged/checkpointed but a manual browser
session on the same account is still working fine.

The cookie value is entered via a hidden prompt and never printed or logged.

Usage:
    python -m app.scraper.import_cookie --session ./sessions/burner_1.json
"""
import argparse
import getpass
import json
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", required=True, help="Path to the storage state JSON to update")
    args = parser.parse_args()

    li_at = getpass.getpass("Paste the li_at cookie value from Safari (hidden input): ").strip()
    if not li_at:
        print("No value entered, aborting.")
        return

    with open(args.session) as f:
        data = json.load(f)

    cookies = data.get("cookies", [])
    expires = time.time() + 60 * 60 * 24 * 365  # ~1 year, matches LinkedIn's own li_at lifetime

    replaced = False
    for c in cookies:
        if c.get("name") == "li_at":
            c["value"] = li_at
            c["expires"] = expires
            replaced = True
            break

    if not replaced:
        cookies.append({
            "name": "li_at",
            "value": li_at,
            "domain": ".www.linkedin.com",
            "path": "/",
            "expires": expires,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        })

    data["cookies"] = cookies
    with open(args.session, "w") as f:
        json.dump(data, f)

    print(f"li_at cookie {'replaced' if replaced else 'added'} in {args.session}. Value not printed.")


if __name__ == "__main__":
    main()
