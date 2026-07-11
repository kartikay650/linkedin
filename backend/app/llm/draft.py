import anthropic

from app.config import settings
from app.llm.humanize import humanize_comments
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """You are writing LinkedIn comment replies AS this specific person. The single most important thing: \
the reply must be indistinguishable from something they wrote themselves. Not "in their style" — actually theirs.

=== HOW THIS PERSON ACTUALLY WRITES (study this hard) ===
{voice}
=== END ===

{brand}

The post they're replying to:
Author: {author}
\"\"\"
{content}
\"\"\"

Write {count} distinct reply options. Each must:
- Sound exactly like the samples above — same sentence length, same rhythm, same vocabulary level, same amount of hedging or bluntness. If they write short and punchy, you write short and punchy. If they use a specific word, use it.
- Take a real position from their viewpoints. React to a specific detail in the post (a mechanism, a number, a claim that's off), not a generic reaction.
- Add genuine insight, never "Great post" or "So true".
- Be 1 to 3 sentences.

HARD RULES (never break):
- Obey the CTA rules. Never write a call-to-action they wouldn't (e.g. no consumer/retail push if the rules say clinical/B2B only).
- Obey the guardrails. If a natural reply would need a patient case study, an un-cited claim, a sensitive story, or an off-limits subject, do NOT write it — make the point within bounds instead.
- Never invent statistics, study results, case studies, or credentials. Only use specifics from the brand profile or the post itself.

NEVER write like AI. Banned: em dashes as connectors, rule-of-three lists ("X, Y, and Z"), "game-changing / unlock / elevate / the future of / crucial / pivotal / delve / testament / underscore", "studies show / experts believe / it's well known", filler openers ("It's worth noting", "Interestingly"), and hedging everything into mush. Real people are lopsided and commit to a point.

Respond ONLY with JSON: {{"drafts": ["option one", "option two", ...]}}"""

REFINE_PROMPT = """Revise this LinkedIn comment, written AS this person, following the operator's instruction. \
Keep it unmistakably in their voice.

=== HOW THIS PERSON ACTUALLY WRITES ===
{voice}
=== END ===

The post being replied to:
\"\"\"
{content}
\"\"\"

Current reply:
\"\"\"
{current}
\"\"\"

Operator's instruction: {instruction}

Rewrite the reply to follow that instruction while staying in their exact voice. No em dashes, no rule-of-three, \
no promotional or AI words, no invented facts. Commit to a specific point. Respond ONLY with JSON: {{"draft": "..."}}"""


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
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                count=count,
                voice=_voice_block(client),
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
    return humanize_comments(drafts, _voice_block(client))


def refine_draft(client: Client, post: Post, current_text: str, instruction: str) -> str:
    """Revise a single draft per an operator instruction (e.g. 'shorter', 'more personal')."""
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": REFINE_PROMPT.format(
                voice=_voice_block(client),
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
