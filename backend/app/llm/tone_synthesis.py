import anthropic

from app.config import settings
from app.llm.utils import extract_json
from app.models import Client, ClientDocument

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """You're helping build a voice/tone profile for a LinkedIn client based on real source material \
(interview transcripts, writing samples, bios). This profile will be used to draft LinkedIn comment replies \
that should sound authentically like this person.

Client: {name}, {specialty}

Source material:
\"\"\"
{sources}
\"\"\"

Write a short tone profile (voice, do's/don'ts, a few sample phrases) based ONLY on patterns you can actually \
observe in the source material above — specific word choices, sentence rhythm, recurring stances or pet peeves, \
level of formality. Do not invent traits that aren't evidenced in the text. If the material is too thin to infer \
something (e.g. no examples of a certain register), leave it out rather than guessing.

Respond ONLY with JSON: {{"tone_profile": "..."}}"""


def synthesize_tone_profile(client: Client, documents: list[ClientDocument]) -> str:
    sources = "\n\n---\n\n".join(d.extracted_text for d in documents if d.extracted_text)
    message = _client.messages.create(
        model=settings.draft_model,
        max_tokens=800,
        messages=[{
            "role": "user",
            "content": PROMPT.format(name=client.name, specialty=client.specialty, sources=sources),
        }],
    )
    try:
        data = extract_json(message)
        return str(data["tone_profile"])
    except (ValueError, KeyError):
        return ""
