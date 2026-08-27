from app.llm._llm import AzureClient

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, Post

_client = AzureClient()

PROMPT = """You score whether a LinkedIn post is worth this client commenting on.

Client specialty: {specialty}
Client topics of interest: {topics}

Who the client is trying to reach (their audience and that audience's pain points):
\"\"\"
{audience}
\"\"\"

The client's own stances/opinions in this field (a comment is high-value when the client can add one of
these specific viewpoints to the conversation):
\"\"\"
{viewpoints}
\"\"\"

Post author: {author}
Post content:
\"\"\"
{content}
\"\"\"

Score relevance from 0.0 to 1.0. Reward posts where (a) the topic genuinely fits the client's expertise,
(b) the client could add value FOR THE AUDIENCE above — not just react generically, and (c) the client has
a specific viewpoint that would make the comment substantive. Penalise generic filler and posts where a
comment would just be polite noise.

Also write a "summary": one plain sentence saying what the post is actually about, so a reviewer can decide
whether to open it without reading the whole thing. No hype, no adjectives, just the gist.

Respond ONLY with JSON: {{"score": float, "reason": "one sentence", "summary": "one sentence"}}"""


def score_post(client: Client, post: Post) -> tuple[float | None, str, str]:
    """Score 0.0-1.0, or None when scoring failed (leaves the post unscored rather than
    mislabelling it as irrelevant)."""
    message = _client.messages.create(
        model=settings.relevance_model,
        max_tokens=200,
        # Judgement call (does this client have anything real to add?) — give it a reasoning pass.
        effort="low",
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                specialty=client.specialty,
                topics=", ".join(client.topics or []),
                audience=(client.audience or "").strip() or "(not specified)",
                viewpoints=(client.viewpoints or "").strip() or "(not specified)",
                author=post.author_name,
                content=post.content_snippet,
            ),
        }],
    )
    try:
        data = extract_json(message)
        return float(data["score"]), str(data["reason"]), str(data.get("summary", ""))
    except (ValueError, KeyError):
        # Return None, NOT 0.0. A transient API/parse error used to score the post 0 — which now
        # means "junk": hidden from the feed, refused for drafting, and swept by the archive pass.
        # A good post was permanently buried by a blip. Unscored posts stay visible and can be
        # re-scored instead.
        return None, "relevance scoring failed — not scored yet", ""
