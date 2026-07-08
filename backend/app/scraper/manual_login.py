"""One-time interactive login to create/refresh a burner's session file.

Run this locally (not headless — you need to see the browser to solve any
LinkedIn checkpoint/2FA prompt yourself), then copy the resulting storage
state file onto the VM at the path referenced by that burner's `storage_state_path`.

Usage:
    python -m app.scraper.manual_login --out ./sessions/burner_1.json
"""
import argparse

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Path to write the session storage state JSON to")
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.linkedin.com/login")

        print("Log in manually in the opened browser window (solve any checkpoint/2FA).")
        input("Once you're fully logged in and see your feed, press Enter here to save the session... ")

        context.storage_state(path=args.out)
        print(f"Session saved to {args.out}")

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
