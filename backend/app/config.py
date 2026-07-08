from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://linkedin:linkedin@postgres:5432/linkedin"
    redis_url: str = "redis://redis:6379/0"

    anthropic_api_key: str = ""
    relevance_model: str = "claude-haiku-4-5-20251001"
    draft_model: str = "claude-sonnet-5"

    packetstream_username: str = ""
    packetstream_password: str = ""
    packetstream_host: str = "proxy.packetstream.io"
    packetstream_port: int = 31112

    alert_webhook_url: str = ""  # Slack/Telegram incoming webhook

    # Safety defaults — intentionally not exposed to the dashboard/ops UI.
    max_actions_per_burner_per_day: int = 20
    min_delay_seconds: int = 45
    max_delay_seconds: int = 180
    health_check_interval_minutes: int = 60

    class Config:
        env_file = ".env"


settings = Settings()
