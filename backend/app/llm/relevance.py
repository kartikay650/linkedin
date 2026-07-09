import anthropic

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

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
comment would just be polite noise. Respond ONLY with JSON: {{"score": float, "reason": "one sentence"}}"""


def score_post(client: Client, post: Post) -> tuple[float, str]:
    message = _client.messages.create(
        model=settings.relevance_model,
        max_tokens=200,
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
        return float(data["score"]), str(data["reason"])
    except (ValueError, KeyError):
        return 0.0, "relevance scoring failed to parse a response"
