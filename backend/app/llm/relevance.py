import anthropic

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """You score whether a LinkedIn post is worth this client commenting on.

Client specialty: {specialty}
Client topics of interest: {topics}

Post author: {author}
Post content:
\"\"\"
{content}
\"\"\"

Score relevance from 0.0 to 1.0: does this post genuinely fit the client's expertise/audience,
is it recent/active enough that a comment would still get seen, and does it have real substance
(not generic filler) worth engaging with. Respond ONLY with JSON: {{"score": float, "reason": "one sentence"}}"""


def score_post(client: Client, post: Post) -> tuple[float, str]:
    message = _client.messages.create(
        model=settings.relevance_model,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                specialty=client.specialty,
                topics=", ".join(client.topics or []),
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
