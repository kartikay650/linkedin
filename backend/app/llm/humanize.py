"""Humanizer pass — strips AI writing tells from generated comment drafts and
matches the client's own voice. Adapted from the `humanizer-blader` skill
(Wikipedia "Signs of AI writing"), scoped to short LinkedIn comments.

Runs as a second pass after draft generation: generate for substance/stance,
then humanize for how it reads. Falls back to the original text on any failure
so a draft is never lost.
"""
import anthropic

from app.config import settings
from app.llm.utils import extract_json

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """Rewrite each of these LinkedIn comment drafts so it reads like a real person typed it, not an AI. \
Keep each one SHORT (1-3 sentences), keep its core point and any specific detail/number/mechanism it cites, and \
do not add new claims, statistics, or anecdotes.

Match this person's voice:
\"\"\"
{voice}
\"\"\"

Remove these AI tells (from the "signs of AI writing" guide):
- Em dash as a crutch — use a period or comma like people do. At most one em dash across all drafts.
- Rule of three ("X, Y, and Z"). Real comments are lopsided, not neatly balanced triplets.
- Promotional / inflated words: vibrant, rich, profound, groundbreaking, game-changing, unlock, elevate, "the future of", crucial, pivotal, vital, seamless.
- "AI vocabulary": delve, tapestry, testament, underscore, showcase, foster, intricate, landscape (abstract), interplay, align with, robust, leverage.
- Copula avoidance ("serves as", "stands as", "boasts") — just use is/are/has.
- Vague attribution ("studies show", "experts believe", "it's well known"). Be specific or drop it.
- Filler openers ("It's worth noting", "Interestingly", "In today's world").
- Negative parallelism ("not just X, but Y") and clipped tailing negations ("no guessing").
- Superficial "-ing" tails that fake depth ("highlighting the importance of...", "reflecting a broader...").
- Every sentence the same length. Vary the rhythm; a fragment is fine.

Also remove these LinkedIn-comment tells specifically:
- Exclamation points. No exclamation points at all.
- The author's name at the start. Names go at the end after a comma, only when natural.
- Praise / summary openers: "Great post", "Great point", "Love this", "Insightful", "Absolutely", "Couldn't agree more", "What stood out to me is", "You make a great point about".
- Evaluating how the post was written ("the way you've framed this", "you've articulated this", "your observation about X"). React to the idea, not the author's performance.
- The nominalized-insight formula: [abstract noun phrase wrapping the post] + is + [meta-claim about what most people/frameworks miss, or how significant it is]. This is the single most common tell. It includes openers like "The idea that...", "The gap between X and Y...", "The question of whether...", "The distinction between X and Y...", "That gap between X and Y is where...", closed by "...is the part most frameworks don't account for", "...is something most people don't measure", "...is where most of my job happens". Say the point plainly instead. Rewrite these exactly like the GOOD versions:
  BAD: "The gap between feeling alive and merely being alive is something most health frameworks don't measure."
  GOOD: "Most health metrics stop at alive and never get near what it means to actually feel good."
  BAD: "The question of whether we're reducing weight or improving metabolic function is one that applies well beyond PCOS."
  GOOD: "Weight loss and metabolic health are not the same thing, and it shows up way beyond PCOS."
  BAD: "That gap between a p-value and a person is where most of my job happens."
  GOOD: "Physicians remember the one patient whose result made no sense on paper. That's usually when the science starts to matter to them."
- "Reminder" framing ("powerful reminder", "serves as a reminder"), rarity flattery ("rare to see", "so refreshing"), abstract gratitude ("thanks for these valuable insights").

GOLDEN RULE: react to the SUBJECT of the post, not to the post itself or how it was written. Pick ONE specific thing from the post. If the comment could sit under any post in this niche, rewrite it so it only makes sense under this one.

Keep it committed on her actual viewpoint and specific — a real expert takes a position, they don't hedge into \
mush. BUT do not sound more certain than the science: these are scientists and the field is rarely black-and-white. \
Cut absolutes and false precision ("exactly", "almost exactly", "matches it exactly", "proven", "definitely", \
"always", "guarantees", a mechanism stated as settled fact) and prefer measured phrasing ("tends to", "seems to", \
"often", "may", "one likely reason", "points toward", "consistent with"). Nuance over black-and-white. This is about \
the certainty of claims, not personality, so stay committed and specific — just don't overstate the evidence. \
No emoji unless the voice explicitly uses them. Keep it to at most three sentences. Do not make it longer than the original.

Drafts:
{drafts}

Respond ONLY with JSON: {{"drafts": ["rewritten one", "rewritten two", ...]}} in the same order and count."""


def humanize_comments(texts: list[str], voice_guide: str) -> list[str]:
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return texts
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    try:
        message = _client.with_options(max_retries=1, timeout=40.0).messages.create(
            model=settings.draft_model,
            max_tokens=700,
            extra_body={"thinking": {"type": "disabled"}},  # mechanical rewrite — no thinking, keeps us under 60s
            messages=[{
                "role": "user",
                "content": PROMPT.format(voice=(voice_guide or "").strip() or "Direct, plain, no fluff.", drafts=numbered),
            }],
        )
        data = extract_json(message)
        out = [str(d) for d in data["drafts"] if str(d).strip()]
        # Only trust the rewrite if it returned the same number of drafts; otherwise keep originals.
        return out if len(out) == len(texts) else texts
    except Exception:
        # Never lose a draft to a humanizer hiccup — fall back to the originals.
        return texts
