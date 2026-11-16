"""Shared fixtures. Nothing here touches Supabase, Azure or Apify.

Run from backend/ (pytest is not in requirements.txt, to keep it out of the Vercel bundle):
    pip install -r requirements.txt pytest && python -m pytest tests
The database is an in-memory SQLite built from the models, and every LLM or HTTP call is blocked
unless a test replaces it with a fake, so a test can never spend money or write to production.
"""
import os
import sys

# Before anything imports app.config: no .env, no real database, no keys.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SERVERLESS"] = "false"
os.environ["AZURE_OPENAI_KEY"] = ""
os.environ["APIFY_TOKEN"] = ""
os.environ["APIFY_TOKENS"] = ""
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base  # noqa: E402
import app.models  # noqa: E402,F401  (registers every table on Base)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP call fails the test."""
    def refuse(*a, **k):
        raise AssertionError(f"a test tried to make a real HTTP call: {a[:1]}")
    for name in ("get", "post", "put", "patch", "delete", "request"):
        monkeypatch.setattr(httpx, name, refuse)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class FakeLLM:
    """Stands in for draft._call: returns queued replies in order and records every prompt."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, model, content, *a, **k):
        from app.llm._llm import _Message
        text = content if isinstance(content, str) else "\n\n".join(b["text"] for b in content)
        self.prompts.append(text)
        if not self.replies:
            raise AssertionError("FakeLLM ran out of replies; an unexpected extra call was made")
        return _Message(self.replies.pop(0))
