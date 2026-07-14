"""Clinical-safety / citation layer.

Two passes, kept separate so the slow web pass never runs inside the draft
request (which must stay under Vercel's 60s ceiling):

1. annotate_provenance() — one fast LLM pass, no web. Splits a drafted reply
   into claim spans and labels each: grounded (drawn from the client's own
   material), general (common knowledge / safe inference), or unverified (a
   specific factual/clinical/statistical claim NOT supported by her material —
   the operator should check it). Green / amber / red in the UI.

2. verify_claims() — explicit, on-demand. Uses Claude's server-side web search
   to check the red claims and attach a source, so a clinical number is either
   cited or flagged as unconfirmed before anyone posts it.
"""
import json
import re

import anthropic
import httpx

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, Post

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _json_from_all_text(message) -> dict:
    """Web-search responses interleave narration and tool-result blocks; the
    final JSON can be in the last text block, not the first. Concatenate every
    text block and parse the outermost {...} span."""
    text = "\n".join(
        b.text for b in message.content
        if getattr(b, "type", None) == "text" and b.text
    )
    cleaned = _FENCE_RE.sub("", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start:end + 1])
    raise ValueError("no parseable JSON object in Claude response")

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _grounding(client: Client, docs_text: str = "") -> str:
    """Everything we treat as 'her own material' — the source of truth a claim
    can be grounded against."""
    parts = []
    for label, val in [
        ("Her voice samples", client.voice_samples),
        ("Her viewpoints / stances", client.viewpoints),
        ("Key messages / proof points", client.key_messages),
        ("Guardrails", client.guardrails),
    ]:
        if (val or "").strip():
            parts.append(f"{label}:\n{val.strip()}")
    if docs_text.strip():
        parts.append("Uploaded source documents:\n" + docs_text.strip()[:20000])
    return "\n\n".join(parts) if parts else "(no client material on file)"


PROVENANCE_PROMPT = """You are a clinical-safety reviewer for a health expert's LinkedIn comment. \
Your job is to trace where each part of a drafted reply comes from, so a human can catch any claim \
the reply invented.

=== THE CLIENT'S OWN MATERIAL (the only trusted source) ===
{grounding}
=== END ===

The post being replied to:
\"\"\"
{post}
\"\"\"

The drafted reply to review:
\"\"\"
{reply}
\"\"\"

Break the reply into consecutive spans that together reconstruct it exactly (concatenated, in order, \
they equal the reply verbatim). Label each span:
- "grounded": the point is supported by the client's own material above, or by the post itself.
- "general": common knowledge, a hedge, connective phrasing, or a safe qualitative inference — nothing a \
reader could dispute as a factual error.
- "unverified": a SPECIFIC factual, clinical, statistical, or mechanistic claim (a number, a study result, \
a dosage, a named effect) that is NOT supported by the client's material. These are the risky ones.

For each span write a short "note": for grounded, where it comes from; for unverified, what would need checking.

Respond ONLY with JSON:
{{"segments": [{{"text": "...", "level": "grounded|general|unverified", "note": "..."}}]}}"""


def annotate_provenance(client: Client, post: Post, reply: str, docs_text: str = "") -> list[dict]:
    try:
        message = _client.with_options(max_retries=1, timeout=35.0).messages.create(
            model=settings.draft_model,
            max_tokens=1500,
            extra_body={"thinking": {"type": "disabled"}},  # classification pass — no thinking, keeps route under 60s
            messages=[{
                "role": "user",
                "content": PROVENANCE_PROMPT.format(
                    grounding=_grounding(client, docs_text),
                    post=post.content_snippet,
                    reply=reply,
                ),
            }],
        )
        data = extract_json(message)
        segments = list(data["segments"])
    except (ValueError, KeyError, anthropic.AnthropicError):
        # Never block drafting on the safety layer — degrade to "unknown".
        return [{"text": reply, "level": "general", "note": ""}]
    # Guard: only keep well-formed spans.
    out = []
    for s in segments:
        if isinstance(s, dict) and s.get("text"):
            lvl = s.get("level")
            out.append({
                "text": str(s["text"]),
                "level": lvl if lvl in ("grounded", "general", "unverified") else "general",
                "note": str(s.get("note", "")),
                "source_url": s.get("source_url", ""),
            })
    return out or [{"text": reply, "level": "general", "note": ""}]


VERIFY_PROMPT = """You are fact-checking the clinical/statistical claims in a health expert's drafted \
LinkedIn comment before it is posted. Use web search to check each flagged claim against reputable sources \
(peer-reviewed studies, medical bodies, established health publications).

The drafted reply:
\"\"\"
{reply}
\"\"\"

Claims to verify (these were flagged as specific factual claims not backed by the client's own material):
{claims}

For each claim, search the web, then decide:
- "supported": reputable sources back it — include the single best source URL.
- "unconfirmed": you could not find reputable support — the operator must remove or soften it.
- "contradicted": reputable sources disagree — flag it clearly.

Respond ONLY with JSON:
{{"results": [{{"claim": "...", "verdict": "supported|unconfirmed|contradicted", "source_url": "...", "note": "one sentence"}}]}}"""


def verify_claims(reply: str, flagged: list[str]) -> list[dict]:
    """Web-verify the flagged (red) claims. Explicit, on-demand.

    A web-search agentic loop is unbounded, but the serverless function has a
    hard 60s ceiling — so cap the work (at most 3 claims, few searches) and give
    the API call a 45s budget. If it runs long, we return 'unconfirmed' rather
    than letting the whole request die at the edge."""
    if not flagged:
        return []
    flagged = flagged[:3]
    claims_block = "\n".join(f"- {c}" for c in flagged)
    timed_out = [{"claim": c, "verdict": "unconfirmed", "source_url": "",
                  "note": "couldn't confirm in time — please check manually"} for c in flagged]

    # Call the web-search tool over raw HTTP: the pinned SDK (0.34.2) can't
    # deserialize the web_search_tool_result / server_tool_use blocks the response
    # carries, so going through the SDK raised and always fell back. Raw JSON works
    # regardless of SDK/model/tool version.
    body = {
        "model": settings.draft_model,
        "max_tokens": 1500,
        "tools": [{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
        "messages": [{"role": "user", "content": VERIFY_PROMPT.format(reply=reply, claims=claims_block)}],
    }
    headers = {
        "x-api-key": settings.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", json=body, headers=headers, timeout=48.0)
        if r.status_code != 200:
            print(f"[verify] web search HTTP {r.status_code}: {r.text[:200]}")
            return timed_out
        data = r.json()
        text = "\n".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        cleaned = _FENCE_RE.sub("", text).strip()
        start, end = cleaned.find("{"), cleaned.rfind("}")
        parsed = json.loads(cleaned[start:end + 1]) if start != -1 and end > start else {}
        return list(parsed.get("results", [])) or timed_out
    except Exception as ex:  # network / parse / timeout — never break the endpoint
        print(f"[verify] {type(ex).__name__}: {ex}")
        return timed_out
