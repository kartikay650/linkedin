import anthropic

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, ClientDocument

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """You are extracting a structured brand profile for a LinkedIn client from their agency \
strategy document(s) and any interviews/transcripts provided. This profile drives two things: (1) deciding \
which posts are worth the client commenting on, and (2) drafting comment replies that sound authentically \
like this person and stay on-brand. Extract ONLY what the source material actually supports — do not invent \
positions, facts, or claims. If a section is thin, keep it short rather than padding it.

Client (may be blank — infer from the material if so): {name}, {specialty}

Source material:
\"\"\"
{sources}
\"\"\"

Produce these sections:

- name: the client's full name exactly as it appears in the material (e.g. "Dr. Jane Smith"). Empty string if truly not stated.
- specialty: their professional specialty/field in a few words (e.g. "Cardiology", "Longevity & preventive medicine").

- voice_guide: How this person writes. Tone, register, sentence rhythm, recurring habits, explicit do's and \
don'ts, and a few short sample phrasings drawn from the material. This is for imitating their voice.

- viewpoints: Their actual stances and opinions on topics in their field — the specific, sometimes \
contrarian positions they hold (e.g. what they think is overhyped, what the mainstream gets wrong). A reply \
should be able to take a real position, so capture concrete opinions, not neutral summaries.

- audience: Who they are trying to reach and that audience's specific pain points. This decides post \
relevance: a post is worth engaging when the client could add value FOR THIS AUDIENCE.

- key_messages: Their core positioning statements and proof points — the handful of things they consistently \
want to reinforce.

- cta_rules: How and when they point people to resources, and — critically — what they must NOT do (e.g. any \
"do not push consumer purchase" type rules, preferred call-to-action language).

- guardrails: Hard rules the drafter must never violate. Include anything in the material about content that \
needs approval, is off-limits, or is sensitive (e.g. case studies requiring sign-off, specific stories not to \
be used, claims that must be cited, subjects to avoid). Phrase each as a clear rule.

- topics: A flat list of the subjects/keywords central to this client's field (for matching relevant posts).

- suggested_creators: People named in the material as worth watching or engaging with. For each, give name, \
profile_url, and a one-line reason. IMPORTANT: the material may end with a "[LinkedIn profile links referenced \
in this document]" list — match each person to their profile URL from that list using the name in the URL slug \
(e.g. "/in/delphine-legrand..." → Delphine LeGrand), and put it in profile_url. These links are authoritative; \
prefer them over any guess. Leave profile_url empty only if there's genuinely no matching link.

Respond ONLY with JSON:
{{"name": "...", "specialty": "...", "voice_guide": "...", "viewpoints": "...", "audience": "...", \
"key_messages": "...", "cta_rules": "...", "guardrails": "...", "topics": ["..."], \
"suggested_creators": [{{"name": "...", "profile_url": "...", "reason": "..."}}]}}"""


# Cap combined source text so one extraction call stays well under the serverless
# time limit even when several long docs (e.g. a full interview transcript) are
# uploaded at once. ~60k chars ≈ 15k tokens — plenty of signal for a brand profile.
_MAX_SOURCE_CHARS = 60000


def extract_brand_profile(client: Client, documents: list[ClientDocument]) -> dict:
    sources = "\n\n---\n\n".join(d.extracted_text for d in documents if d.extracted_text)
    sources = sources[:_MAX_SOURCE_CHARS]
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": PROMPT.format(name=client.name, specialty=client.specialty, sources=sources),
        }],
    )
    try:
        data = extract_json(message)
    except ValueError:
        return {}

    # Normalise: guarantee every field exists with the right type so the schema validates.
    def _s(key):
        v = data.get(key)
        return v if isinstance(v, str) else ""

    topics = data.get("topics")
    topics = [str(t) for t in topics] if isinstance(topics, list) else []

    creators = []
    raw_creators = data.get("suggested_creators")
    if isinstance(raw_creators, list):
        for c in raw_creators:
            if isinstance(c, dict) and c.get("name"):
                creators.append({
                    "name": str(c.get("name", "")),
                    "profile_url": str(c.get("profile_url") or ""),
                    "reason": str(c.get("reason") or ""),
                })

    return {
        "name": _s("name"),
        "specialty": _s("specialty"),
        "voice_guide": _s("voice_guide"),
        "viewpoints": _s("viewpoints"),
        "audience": _s("audience"),
        "key_messages": _s("key_messages"),
        "cta_rules": _s("cta_rules"),
        "guardrails": _s("guardrails"),
        "topics": topics,
        "suggested_creators": creators,
    }
