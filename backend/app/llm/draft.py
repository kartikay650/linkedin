import anthropic

from app.config import settings
from app.llm.humanize import humanize_comments
from app.llm.style import HOUSE_STYLE, STRONG_EXAMPLES
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """You are writing ONE LinkedIn comment reply AS {name}. The single most important thing: the reply must be \
indistinguishable from something she typed herself. Not "in her style" — actually hers.

=== HOW SHE ACTUALLY WRITES (study this hard, match it exactly) ===
{voice}
=== END ===

{brand}

{house_style}

{examples}

The post she is replying to:
Author: {author}
\"\"\"
{content}
\"\"\"

Write ONE reply that:
- sounds exactly like her voice samples above — same sentence length, rhythm, vocabulary level, and bluntness,
- reacts to one specific thing in THIS post, never a generic reaction that could sit under any post,
- states one of her real positions (from the brand context) where it fits, in plain spoken language,
- obeys every house-style and content-safety rule above, and obeys her CTA rules and guardrails.

Respond ONLY with JSON: {{"drafts": ["your one reply"]}}"""

REFINE_PROMPT = """Revise this LinkedIn comment, written AS {name}, following the operator's instruction. \
Keep it unmistakably in her voice and obey every house-style rule.

=== HOW SHE ACTUALLY WRITES ===
{voice}
=== END ===

{house_style}

The post being replied to:
\"\"\"
{content}
\"\"\"

Current reply:
\"\"\"
{current}
\"\"\"

Operator's instruction: {instruction}

Rewrite the reply to follow that instruction while staying in her exact voice and inside every house-style and \
content-safety rule above. Respond ONLY with JSON: {{"draft": "..."}}"""


def _voice_block(client: Client) -> str:
    """The person's real voice: verbatim samples first (strongest signal), then the
    written description. Falls back to the legacy tone_profile."""
    parts = []
    if (client.voice_samples or "").strip():
        parts.append("Verbatim examples of their own words:\n" + client.voice_samples.strip())
    guide = (client.voice_guide or client.tone_profile or "").strip()
    if guide:
        parts.append("How they write:\n" + guide)
    return "\n\n".join(parts) if parts else "Direct, plain, specific. No fluff."


def _brand_block(client: Client) -> str:
    sections = [
        ("Their viewpoints / stances", client.viewpoints),
        ("Audience they're speaking to", client.audience),
        ("Key messages / proof points", client.key_messages),
        ("CTA rules", client.cta_rules),
        ("Guardrails (hard rules)", client.guardrails),
    ]
    parts = [f"{label}:\n{value.strip()}" for label, value in sections if value and value.strip()]
    return ("=== BRAND CONTEXT ===\n" + "\n\n".join(parts) + "\n=== END ===") if parts else ""


def generate_drafts(client: Client, post: Post, count: int = 2) -> list[str]:
    message = _client.with_options(max_retries=1, timeout=45.0).messages.create(
        model=settings.draft_model,
        max_tokens=800,
        thinking={"type": "disabled"},  # the house-style prompt + few-shot do the work; keeps the 3-call route fast
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                name=client.name,
                voice=_voice_block(client),
                brand=_brand_block(client),
                house_style=HOUSE_STYLE,
                examples=STRONG_EXAMPLES,
                author=post.author_name,
                content=post.content_snippet,
            ),
        }],
    )
    try:
        data = extract_json(message)
        drafts = list(data["drafts"])
    except (ValueError, KeyError):
        return []
    return humanize_comments(drafts, _voice_block(client))


def refine_draft(client: Client, post: Post, current_text: str, instruction: str) -> str:
    """Revise a single draft per an operator instruction (e.g. 'shorter', 'more personal')."""
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": REFINE_PROMPT.format(
                name=client.name,
                voice=_voice_block(client),
                house_style=HOUSE_STYLE,
                content=post.content_snippet,
                current=current_text,
                instruction=instruction,
            ),
        }],
    )
    try:
        data = extract_json(message)
        revised = str(data["draft"])
    except (ValueError, KeyError):
        return current_text
    out = humanize_comments([revised], _voice_block(client))
    return out[0] if out else revised
