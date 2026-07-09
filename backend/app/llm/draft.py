import anthropic

from app.config import settings
from app.llm.humanize import humanize_comments
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """Draft {count} short LinkedIn comment replies for this client to post on the post below.

=== CLIENT BRAND PROFILE ===
{brand}
=== END BRAND PROFILE ===

Post author: {author}
Post content:
\"\"\"
{content}
\"\"\"

HARD RULES (never violate, even if a more natural reply would):
- Obey the client's CTA rules exactly. Never write a call-to-action the rules prohibit (for example, never push a consumer/retail purchase if the rules say business/clinical only).
- Obey every rule in the guardrails section. If a natural reply would require content the guardrails restrict — a patient case study, an un-cited claim, a sensitive personal story, an off-limits subject — do NOT write it. Produce a reply that stays inside the bounds instead.
- Never fabricate case studies, patient stories, personal anecdotes, statistics, study results, or credentials. Only state specifics that appear in the brand profile above or in the post itself. When in doubt, make the point without the specific.
- Take a position drawn from the client's actual viewpoints above; never invent an opinion they haven't expressed.

Write like a real scientist/clinician typing a quick comment, not like an AI assistant. Specifically avoid:
- Em dashes as a crutch for every sentence — use a period or comma like a person actually would.
- Rule-of-three lists ("X, Y, and Z") — real comments are lopsided, not neatly balanced.
- Inflated or promotional language: "game-changing," "unlock," "elevate," "the future of," "exciting."
- Vague hand-waving attribution: "studies show," "many experts believe," "it's well known that." If you reference evidence, be specific (a mechanism, a number, a named confound) or don't reference it at all.
- Filler openers: "It's worth noting that," "Interestingly," "In today's world."
- Hedging every claim into mush. A real expert commits to a specific, falsifiable point.

What TO do:
- Lead with the actual point, no windup.
- Reference one concrete, specific detail from the post's content — a mechanism, a missing control, a number that seems off — not a generic reaction to it.
- Sound like a specific person with a specific stance, not a balanced summary of "both sides."
- Add genuine insight — never generic praise like "Great post!" or "So true!".
- Short: 1-3 sentences. No emoji unless the client's tone profile explicitly uses them.
- The goal is to make readers curious enough to click through to the client's profile, not to summarize the post.

Respond ONLY with JSON: {{"drafts": ["draft one", "draft two", ...]}}"""


def _brand_block(client: Client) -> str:
    """Assemble the client's brand profile into a labelled block for the prompt,
    using whichever structured sections are filled in and falling back to the
    legacy tone_profile for voice when voice_guide is empty."""
    sections = [
        ("Voice / how they write", client.voice_guide or client.tone_profile),
        ("Their viewpoints / stances", client.viewpoints),
        ("Audience they're speaking to", client.audience),
        ("Key messages / proof points", client.key_messages),
        ("CTA rules", client.cta_rules),
        ("Guardrails (hard rules)", client.guardrails),
    ]
    parts = [f"{label}:\n{value.strip()}" for label, value in sections if value and value.strip()]
    return "\n\n".join(parts) if parts else "Professional, direct, no fluff."


def generate_drafts(client: Client, post: Post, count: int = 2) -> list[str]:
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                count=count,
                brand=_brand_block(client),
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

    # Second pass: strip AI tells and match the client's voice before the human sees it.
    return humanize_comments(drafts, client.voice_guide or client.tone_profile or "")
