import json
import re

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(message) -> dict:
    """Claude sometimes emits a leading 'thinking' block (no .text) and wraps
    JSON replies in markdown code fences — this strips both before parsing."""
    text_block = next((b for b in message.content if getattr(b, "type", None) == "text"), None)
    if text_block is None or text_block.text is None:
        raise ValueError("no text block in Claude response")

    cleaned = _FENCE_RE.sub("", text_block.text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Tolerate surrounding prose: parse the outermost {...} span.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise ValueError("no parseable JSON object in Claude response")
