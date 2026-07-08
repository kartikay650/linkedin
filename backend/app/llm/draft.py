import anthropic

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """Draft {count} short LinkedIn comment replies for this client to post on the post below.

Client tone/background:
\"\"\"
{tone_profile}
\"\"\"

Post author: {author}
Post content:
\"\"\"
{content}
\"\"\"

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


def generate_drafts(client: Client, post: Post, count: int = 2) -> list[str]:
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                count=count,
                tone_profile=client.tone_profile or "Professional, direct, no fluff.",
                author=post.author_name,
                content=post.content_snippet,
            ),
        }],
    )
    try:
        data = extract_json(message)
        return list(data["drafts"])
    except (ValueError, KeyError):
        return []
