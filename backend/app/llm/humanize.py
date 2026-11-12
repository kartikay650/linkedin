"""Humanizer pass — strips AI writing tells from generated comment drafts and
matches the client's own voice. Adapted from the `humanizer-blader` skill
(Wikipedia "Signs of AI writing"), scoped to short LinkedIn comments.

Runs as a second pass after draft generation: generate for substance/stance,
then humanize for how it reads. Falls back to the original text on any failure
so a draft is never lost.
"""
from app.llm._llm import AzureClient

from app.config import settings
from app.llm.utils import extract_json

_client = AzureClient()

PROMPT = """Rewrite each of these LinkedIn comment drafts so it reads like a real person typed it, not an AI. \
Never make a draft longer than it is. Keep its core point and any specific detail/number/mechanism it cites, and \
do not add new claims, statistics, or anecdotes. You may cut an explanatory clause, or a sentence that repeats \
another; you may not add one.

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
- The author's name at the start, or tacked onto the end after a comma as a sign-off. Most comments need no name at all; if one genuinely helps, it goes where it would fall in speech, often mid-sentence.
- Praise / summary openers: "Great post", "Great point", "Love this", "Insightful", "Absolutely", "Couldn't agree more", "What stood out to me is", "You make a great point about".
- Evaluating how the post was written ("the way you've framed this", "you've articulated this", "your observation about X"). React to the idea, not the author's performance.
- The nominalized-insight formula: [abstract noun phrase wrapping the post] + is + [meta-claim about what most people/frameworks miss, or how significant it is]. This is the single most common tell. It includes openers like "The idea that...", "The gap between X and Y...", "The question of whether...", "The distinction between X and Y...", "That gap between X and Y is where...", closed by "...is the part most frameworks don't account for", "...is something most people don't measure", "...is where most of my job happens". Say the point plainly instead. Rewrite these exactly like the GOOD versions:
  BAD: "The gap between feeling alive and merely being alive is something most health frameworks don't measure."
  GOOD: "Most health metrics stop at alive and never get near what it means to actually feel good."
  BAD: "The question of whether we're reducing weight or improving metabolic function is one that applies well beyond PCOS."
  GOOD: "Losing weight and fixing metabolic health get mixed up well beyond PCOS."
  BAD: "That gap between a p-value and a person is where most of my job happens."
  GOOD: "Physicians remember the one patient whose result made no sense on paper, and that's usually when the science starts to matter to them."
- "Reminder" framing ("powerful reminder", "serves as a reminder"), rarity flattery ("rare to see", "so refreshing"), abstract gratitude ("thanks for these valuable insights").

Keep each draft in this person's voice, and do NOT change how opinionated or how scientific it is: if a draft \
is a warm, personal, or simply curious reply, keep it that way — do not make it more assertive, do not add a stance \
or opinion it doesn't already have, and do not turn it analytical. When a draft DOES take a position, keep it \
committed, not hedged into mush. BUT do not sound more certain than the science: these are scientists and the field is rarely black-and-white. \
Cut absolutes and false precision ("exactly", "almost exactly", "matches it exactly", "proven", "definitely", \
"always", "guarantees", a mechanism stated as settled fact). Do NOT use "tends to" or "seems to" — they have become \
an AI tic; state the point plainly, and only hedge when genuinely needed, varying the words. Also remove the over-used \
"[X] shows up / appears in [the body / your markers] [years / decades] before [symptoms / a diagnosis / a scan]" \
construction — say the underlying idea a different way or drop it. Nuance means not overstating the evidence, not \
sprinkling hedge words. Do not pad or trim a draft to a word count; the length was chosen for this post.

SAID TWICE. This is the thing that most makes our comments read as machine-written. When one sentence \
mostly re-says another, hands the post's own point back, or generalises the other into a principle, DELETE it, \
whichever one it is. When two short statements are really one thought, say them as one sentence the way a person \
would; there is no required joining word. Leave two sentences alone when each does different work and both already \
read as speech. \
  REPEATS: "Once a woman has a label, everyone stops looking. A diagnosis can end the investigation." \
  FIXED:   "Once a woman has a label, everyone stops looking." \
  LEAVE IT: "Quite a pairing for 2027. The New York programme should be worth the trip." \
No emoji unless the voice explicitly uses them.

Match this person's voice:
\"\"\"
{voice}
\"\"\"

{keep}Drafts:
{drafts}

Respond ONLY with JSON: {{"drafts": ["rewritten one", "rewritten two", ...]}} in the same order and count."""

# The static rule block (everything before the per-client voice) is identical on every
# call, so we cache it. The variable tail starts at this marker.
_HUMANIZE_SPLIT = "Match this person's voice:"


def keep_note(keep: str, what: str) -> str:
    """One line telling a pass that runs after the Tweak model what the reviewer asked for, so it
    does not undo it. Only the Tweak path passes `keep`; with it empty this returns "" and every
    first-draft prompt is byte-identical to before."""
    keep = " ".join((keep or "").split())
    if not keep:
        return ""
    return (f'A reviewer asked for this change, and {what} already makes it: "{keep[:500]}". '
            "Do not undo it or cut what it added.\n\n")


def humanize_comments(texts: list[str], voice_guide: str, keep: str = "") -> list[str]:
    """`keep` is a reviewer's Tweak request, passed only on the Tweak path. This pass never saw
    the request, so it could read a sentence she had just asked for as a repeat and delete it, or
    smooth a firmer line she asked for back down. With `keep` empty the prompt is byte-identical to
    a first draft's."""
    texts = [t for t in texts if t and t.strip()]
    if not texts:
        return texts
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    full = PROMPT.format(voice=(voice_guide or "").strip() or "Direct, plain, no fluff.", drafts=numbered,
                         keep=keep_note(keep, "the draft"))
    idx = full.find(_HUMANIZE_SPLIT)
    static, variable = full[:idx].rstrip(), full[idx:]
    content = [
        {"type": "text", "text": static, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": variable},
    ]
    try:
        message = _client.with_options(max_retries=1, timeout=40.0).messages.create(
            model=settings.draft_model,
            max_tokens=700,
            effort="low",  # deciding whether a sentence repeats another is a judgement call
            messages=[{"role": "user", "content": content}],
        )
        data = extract_json(message)
        out = [str(d) for d in data["drafts"] if str(d).strip()]
        # Only trust the rewrite if it returned the same number of drafts; otherwise keep originals.
        return out if len(out) == len(texts) else texts
    except Exception:
        # Never lose a draft to a humanizer hiccup — fall back to the originals.
        return texts
