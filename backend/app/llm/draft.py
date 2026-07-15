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

{benchmark}

{feedback}

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

{benchmark}

{feedback}

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
        ("Their personal why / stories (use for genuine human touch, never fabricate)", client.personal_story),
        ("CTA rules", client.cta_rules),
        ("Guardrails (hard rules)", client.guardrails),
    ]
    parts = [f"{label}:\n{value.strip()}" for label, value in sections if value and value.strip()]
    return ("=== BRAND CONTEXT ===\n" + "\n\n".join(parts) + "\n=== END ===") if parts else ""


def _benchmark_block(client: Client) -> str:
    """Operator-curated ideal / non-ideal examples for THIS client (few-shot anchor)."""
    ex = (getattr(client, "benchmark_examples", "") or "").strip()
    if not ex:
        return ""
    return (
        "=== APPROVED EXAMPLES FOR THIS CLIENT (match this tone exactly — hand-picked as ideal/non-ideal) ===\n"
        + ex
        + "\n=== END ==="
    )


def _feedback_block(client: Client) -> str:
    """Most recent operator corrections, auto-applied to every new draft."""
    notes = getattr(client, "feedback", None) or []
    recent = sorted(notes, key=lambda f: f.id, reverse=True)[:5]
    lines = "\n".join(f"- {n.note.strip()}" for n in recent if (n.note or "").strip())
    if not lines:
        return ""
    return (
        "=== OPERATOR GUIDANCE (recent corrections — apply every one) ===\n"
        + lines
        + "\n=== END ==="
    )


def generate_drafts(client: Client, post: Post, count: int = 2) -> list[str]:
    message = _client.with_options(max_retries=1, timeout=45.0).messages.create(
        model=settings.draft_model,
        max_tokens=800,
        # Disable server-side default thinking (via extra_body — the pinned SDK predates the kwarg).
        # Generation focuses on substance/stance; the humanizer pass below then rewrites for how it
        # reads (a dedicated cleanup pass enforces the structural bans far better than one overloaded call).
        extra_body={"thinking": {"type": "disabled"}},
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                name=client.name,
                voice=_voice_block(client),
                brand=_brand_block(client),
                house_style=HOUSE_STYLE,
                examples=STRONG_EXAMPLES,
                benchmark=_benchmark_block(client),
                feedback=_feedback_block(client),
                author=post.author_name,
                content=post.content_snippet,
            ),
        }],
    )
    try:
        data = extract_json(message)
        drafts = [str(d) for d in data["drafts"] if str(d).strip()]
    except (ValueError, KeyError):
        return []
    return humanize_comments(drafts, _voice_block(client))


def refine_draft(client: Client, post: Post, current_text: str, instruction: str) -> str:
    """Revise a single draft per an operator instruction (e.g. 'shorter', 'more personal')."""
    message = _client.with_options(max_retries=1, timeout=45.0).messages.create(
        model=settings.draft_model,
        max_tokens=800,
        extra_body={"thinking": {"type": "disabled"}},  # single-call refine — house style carries the AI-tell bans
        messages=[{
            "role": "user",
            "content": REFINE_PROMPT.format(
                name=client.name,
                voice=_voice_block(client),
                house_style=HOUSE_STYLE,
                benchmark=_benchmark_block(client),
                feedback=_feedback_block(client),
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
