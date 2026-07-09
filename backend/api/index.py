"""Vercel serverless entrypoint. Vercel's Python runtime serves the ASGI `app`
exposed here. We add the backend root to sys.path so `app.*` imports resolve when
the function runs from the api/ directory."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402  (path insert must happen first)
