import httpx

from app.config import settings


def send_alert(message: str) -> None:
    """Fire-and-forget alert to the configured Slack/Telegram webhook.
    Never raises — an alerting bug should never take down the job that triggered it."""
    if not settings.alert_webhook_url:
        return
    try:
        httpx.post(settings.alert_webhook_url, json={"text": message}, timeout=5.0)
    except Exception:
        pass
