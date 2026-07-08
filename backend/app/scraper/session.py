import os
from contextlib import contextmanager

from playwright.sync_api import sync_playwright

from app.config import settings
from app.models import Burner


class CheckpointDetected(Exception):
    """Raised when LinkedIn shows a login/checkpoint/CAPTCHA page instead of real content."""


def _proxy_config() -> dict | None:
    if not settings.packetstream_username:
        return None
    return {
        "server": f"http://{settings.packetstream_host}:{settings.packetstream_port}",
        "username": settings.packetstream_username,
        "password": settings.packetstream_password,
    }


@contextmanager
def burner_page(burner: Burner):
    """Yields a logged-in Playwright page for the given burner, using its persisted session.
    Raises CheckpointDetected if LinkedIn is challenging the session instead of showing real content."""
    if not os.path.exists(burner.storage_state_path):
        raise RuntimeError(
            f"No session file at {burner.storage_state_path}. "
            f"Run the one-time manual login script for burner {burner.id} first."
        )

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            storage_state=burner.storage_state_path,
            proxy=_proxy_config(),
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        try:
            yield page
            _assert_not_checkpointed(page)
            # Only persist the session if it's still actually logged in — saving a
            # logged-out/checkpointed state here would permanently corrupt the file.
            context.storage_state(path=burner.storage_state_path)
        finally:
            context.close()
            browser.close()


def _assert_not_checkpointed(page) -> None:
    url = page.url
    if "checkpoint" in url or "/authwall" in url or "login" in url:
        raise CheckpointDetected(f"burner landed on {url} — session likely needs manual re-login")
