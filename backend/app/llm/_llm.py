"""Azure OpenAI client, shaped like the Anthropic SDK we migrated off.

The rest of the LLM code was written against `anthropic.Anthropic`:
`_client.with_options(...).messages.create(model=..., max_tokens=..., messages=[...])`
returning a message whose `.content[0].text` holds the reply, parsed by
`extract_json`. This module exposes an `AzureClient` with that exact surface so
those call sites need only swap the constructor — nothing downstream changes.

Calls go to Azure OpenAI over httpx (already a dependency; no openai/anthropic
SDK). `model` is an Azure *deployment name* (settings.draft_model /
relevance_model). Prompt caching is automatic on Azure, so the old
`cache_control` blocks are simply flattened to text here and cost nothing extra.
"""
import time

import httpx

from app.config import settings


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text or ""


class _Message:
    """Mimics an anthropic message: .content is a list of text blocks."""
    def __init__(self, text):
        self.content = [_Block(text)]


def _split(content):
    """Split prompt content into (system_text, user_text).

    Content is either a plain string or a list of {type,text,cache_control} blocks. Blocks marked
    with cache_control are the STATIC part of the prompt (house style, the fixed write rules, the
    client's voice/brief); the rest is per-request.

    The static part goes into a SYSTEM message and only the variable part into the user message.
    This is what makes Azure's automatic prompt caching actually fire: measured on gpt-5.6-sol,
    an identical ~3.2k-token prefix sent inside one combined user message caches 0% of the time,
    while the same text sent as a system message caches ~99% of it once warm. We were shipping
    everything as one user message, which is why a week of production traffic reported zero cache
    reads. Order matters too — global-static blocks come before per-client ones so different
    clients still share the same cached prefix."""
    if not isinstance(content, list):
        return "", (content or "")
    system = "\n\n".join(
        b["text"] for b in content
        if isinstance(b, dict) and b.get("text") and b.get("cache_control")
    )
    user = "\n\n".join(
        b["text"] for b in content
        if isinstance(b, dict) and b.get("text") and not b.get("cache_control")
    )
    # Never send an empty user turn.
    if not user.strip():
        return "", system
    return system, user


# Running token/cache tally for this process. Prompt caching is worth ~90% off the cached input
# tokens, and it silently stopped working once before (everything was being sent as one user
# message), so keep the numbers observable rather than trusting it.
USAGE = {"calls": 0, "input": 0, "cached": 0, "output": 0}


def _record_usage(u):
    try:
        USAGE["calls"] += 1
        USAGE["input"] += int(u.get("prompt_tokens") or 0)
        USAGE["output"] += int(u.get("completion_tokens") or 0)
        USAGE["cached"] += int((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    except Exception:
        pass


class _Messages:
    def __init__(self, timeout):
        self._timeout = timeout

    def create(self, model=None, max_tokens=800, messages=None, extra_body=None,
               effort=None, **kw):
        system, text = _split(messages[0]["content"])
        url = (
            f"{settings.azure_openai_endpoint}/openai/deployments/{model}"
            f"/chat/completions?api-version={settings.azure_openai_api_version}"
        )
        headers = {"Content-Type": "application/json", "api-key": settings.azure_openai_key}
        msgs = ([{"role": "system", "content": system}] if system.strip() else []) + \
               [{"role": "user", "content": text}]
        body = {
            "messages": msgs,
            # reasoning tokens count toward completion; +900 headroom so a thinking pass can't
            # squeeze out the JSON reply.
            "max_completion_tokens": (max_tokens or 800) + 900,
            # Steps that need JUDGEMENT (drafting, relevance, provenance) pass effort="low" so the
            # model actually deliberates before writing — measured at only ~+1.2s per call, and it
            # is what stops misreads / invented entities / stance errors. Mechanical steps
            # (humanize, tighten, JSON reshaping) stay "none" for speed.
            "reasoning_effort": effort or "none",
        }
        return _Message(self._post(url, headers, body))

    def _post(self, url, headers, body):
        # Keep the retry budget SMALL: this runs inside a 60s serverless request, and a long
        # retry ladder is what pushes a draft over the edge. 3 attempts with short backoff.
        last = ""
        for attempt in range(3):
            try:
                r = httpx.post(url, json=body, headers=headers, timeout=self._timeout)
                if r.status_code == 200:
                    payload = r.json()
                    _record_usage(payload.get("usage") or {})
                    ch = payload["choices"][0]
                    # content_filter / length with empty content -> "" -> caller falls back
                    return ch["message"].get("content") or ""
                msg = r.text[:200]
                # a deployment that rejects reasoning_effort: drop it and retry once
                if r.status_code == 400 and "reasoning_effort" in msg and "reasoning_effort" in body:
                    body = {k: v for k, v in body.items() if k != "reasoning_effort"}
                    continue
                if r.status_code in (429, 500, 502, 503):
                    time.sleep(0.8 * (attempt + 1))
                    last = msg
                    continue
                print(f"[llm] HTTP {r.status_code}: {msg}")
                return ""
            except Exception as ex:  # network / timeout — one quick retry, then give up
                last = f"{type(ex).__name__}: {ex}"
                time.sleep(0.5)
                continue
        print(f"[llm] gave up after retries: {last}")
        return ""


class AzureClient:
    """Drop-in for `anthropic.Anthropic(api_key=...)`."""
    def __init__(self, api_key=None, timeout=45.0, **kw):
        self.messages = _Messages(timeout)

    def with_options(self, timeout=None, max_retries=None, **kw):
        return AzureClient(timeout=timeout or 45.0)
