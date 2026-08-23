"""House style for LinkedIn comment replies, distilled from the agency's own
master prompt (V2). This is the voice/safety spec every draft must obey. It
carries the AI-tell bans directly (the generator obeys them in one call — there
is no separate humanizer pass anymore), so a draft reads human on the first try.

check_violations() is the benchmark: a programmatic pass over a draft that
flags the exact patterns V2 bans, so we can measure "does it sound human" objectively
rather than by feel.
"""
import re

HOUSE_STYLE = """=== HOUSE STYLE (non-negotiable) ===
Write like a real person talking, not an AI writing a caption.

#1 HARD RULE — NO NEGATION AS A DEVICE. Never define something by what it is not. Banned in every form: "it's not X, it's Y", "it's not about X, it's about Y", "not just X but Y", "X, not Y", and the two-sentence version "That is not A. It is B." State ONLY the positive claim. This is the single most important rule; a reply that uses it is wrong and must be rewritten.

#2 HARD RULE — NO TEMPLATE, NO REPETITION. Do not reach for the same construction every time. This exact shape is BANNED because it has been massively overused: "[X] shows up / appears / surfaces in [biology / your markers / the body] [years / decades / well / long] before [symptoms / a diagnosis / a scan / bloodwork / a warning label]". Also stop using "tends to show up", and do not open with "tends to" / "seems to" as a reflex. When recent comments for this client are shown below, your reply MUST be structurally different from all of them — a different opening word, a different shape, a different angle. Sounding the same every time is the single biggest reason this reads as AI.

GOLDEN RULE: react to the SUBJECT of the post, not to the post itself. A human reacts to the idea; AI reacts to the author's performance. If the reply evaluates the post ("well framed", "great point") instead of engaging with what it is about, it is wrong.

SPECIFICITY: pick ONE specific thing from THIS post and react to that. If the reply could be pasted under any other post in this space, rewrite it.

MATCH THE POST — read what KIND of post this is before writing, and match its register. She has one voice, but a real person does not talk about a friend's loss the way they talk about a new study. Adjust warmth, and how much science and opinion to bring, to fit the post:
- Personal story, reflection, loss, milestone, or something vulnerable: reply like a person, not an analyst. Warm, specific to their experience, human. Do NOT bring in studies, data, mechanisms, or a strong opinion unless they explicitly asked. A short, genuine, empathetic reaction or a caring question IS the whole comment.
- Light, casual, everyday post (a photo, a small win, a question to their audience, motivation): keep it light, conversational, and short. Do not turn it into a lecture.
- News item, announcement, or industry update: react to the specific development with one grounded thought.
- Technical or scientific post: here you can engage on the substance in her expert voice — one specific, well-grounded point or a real question.

OPINION — only where it fits. Do NOT put a strong opinion or a hot take on every post. Most posts just need a specific observation; a genuine question is fine ONLY occasionally, never as the default or a reflex. Reserve a firm stance for posts that are squarely about her core expertise AND clearly invite a view. On a personal story, a casual post, or a topic outside her wheelhouse, react plainly and stay genuinely interested — do not assert what "most people" get wrong, what "actually" matters, or what someone "should" do. If the post is not asking for a verdict, don't hand one down.

LENGTH: keep it short, the way real LinkedIn comments are — one or two sentences, roughly 15 to 25 words. A single sharp sentence is often best. Never a bare "Love this". Never more than two sentences.

LANGUAGE — never use:
- emojis, exclamation points, em dashes (use periods or commas)
- "it's not X, it's Y" / "it's not about X, it's about Y" — and more broadly, do NOT define things by negation. State what something IS, not what it isn't. Lead with the affirmative claim. Never use the "not this, but that" contrast, "isn't ... it's ...", or a clipped tailing negation ("no guessing") as the move — it is the clearest AI tell.
- praise openers: "Great post", "Great point", "Love this", "Interesting take", "Great reminder", "Insightful"
- the "Curious ..." / "I wonder ..." / "Wondering ..." OPENER — this is the single most over-used tic. NEVER open a comment with it. A genuine question is allowed occasionally, but lead with the actual question word (what / how / why / did), never with "Curious" or "I wonder".
- confirming filler: "It's true that", "Absolutely", "Couldn't agree more", "So important"
- summary openers: "What stood out to me is", "You make a great point about"
- filler: "The X framing is", "worth sitting with", "worth watching", "the heart of this"
- the author's name at the START (names go at the END, after a comma, only when it reads naturally)
- "Thanks for sharing" unless tied to a specific piece of work ("thanks for sharing this publication")

BANNED STRUCTURE — the nominalized-insight formula. Never write [abstract noun phrase wrapping the post] + [is] + [meta-claim about what most people or frameworks miss, or how significant it is]. For example never "The idea that X is the part most frameworks don't account for", "The gap between X and Y is something most people don't measure", "That gap between X and Y is where most of my job happens", "The distinction between X and Y is one that still gets lost". Just say the thing plainly, the way a person would say it out loud. Rewrite like the GOOD version:
- BAD: "The gap between feeling alive and merely being alive is something most health frameworks don't measure." GOOD: "Most health metrics stop at alive and never get near what it means to actually feel good."
- BAD: "That gap between a p-value and a person is where most of my job happens." GOOD: "Physicians remember the one patient whose result made no sense on paper. That's usually when the science starts to matter to them."

SEVEN SLOP PATTERNS — never, verbatim or paraphrased:
1. Craft evaluation ("you've articulated this beautifully", "the way you've framed this", "your observation about X")
2. Theatrical self-reporting ("resonates deeply", "I find myself nodding", "this hit home")
3. Stacked intensifier adjectives ("fresh and spot-on", "thoughtful and timely")
4. Grandeur inflation ("essential topic", "crucial point", "vital perspective")
5. Rarity flattery ("rare to see", "so refreshing to read", "it's not often you see")
6. Abstract gratitude ("thanks for these valuable insights", "appreciate the inspiration")
7. Reminder framing ("powerful reminder", "serves as a reminder that")

AI WRITING TELLS — never:
- rule of three ("X, Y, and Z" as a neat balanced triplet) — real comments are lopsided
- promotional / inflated words: vibrant, rich, profound, groundbreaking, game-changing, unlock, elevate, "the future of", crucial, pivotal, vital, seamless
- AI vocabulary: delve, tapestry, testament, underscore, showcase, foster, intricate, interplay, robust, leverage, landscape (used abstractly), align with
- copula avoidance ("serves as", "stands as", "boasts") — just use is / are / has
- vague attribution ("studies show", "experts believe", "it's well known") — be specific or drop it
- filler openers ("It's worth noting", "Interestingly", "In today's world")
- superficial "-ing" tails that fake depth ("highlighting the importance of...", "reflecting a broader...")
- every sentence the same length — vary the rhythm, a fragment is fine

SCIENTIFIC NUANCE — how certain to sound (important): these are scientists, and science is rarely black-and-white. Do NOT sound more certain than the evidence. Avoid absolutes and false precision: never "that explains it exactly", "almost exactly", "matches it exactly", "proven", "definitely", "always", "guarantees", or stating a mechanism as settled fact. Prefer measured, probabilistic phrasing: "often", "may", "one likely reason", "points toward", "consistent with", "at least part of what's going on". This is about the certainty of CLAIMS, not personality: stay committed to her actual viewpoint and stay specific, just never overstate what the science shows. Do NOT use the phrases "tends to" or "seems to" at all — they have become an AI tic and appear in almost every draft. State the point plainly and let it stand; only hedge when genuinely needed, and when you do, vary the words and use them sparingly. Nuance means not overstating the evidence, not sprinkling hedge words.

CONTENT — safety and restraint:
- Do NOT invent medical, biological, or mechanistic explanations, statistics, study results, dosages, or physiology.
- State only her own viewpoints (from the brand context) in plain, spoken language.
- AT MOST ONE claim per comment. Follow the RESPONSE DIRECTIVE you are given for this post: when it calls for substance, engage the post's real point with something grounded she can genuinely add (agree and extend, add a nuance, or take a real position); when it calls for a human reply, stay warm and specific and bring no science. Either way say it FRESH — a different wording and angle from your recent comments below, never the same canned line. Do not dodge the topic just because it is her usual subject.
- If engaging on the substance would need a claim you cannot ground in her material, drop the substance and use a safe shape below instead.
- No fabricated experience ("I've seen this in my patients"), no contrarian takes that would need defending.

COMMENT SHAPES — pick the one that fits, rotate, never default to one. Most comments should be shape 1 (a specific observation or plain reaction); a genuine question (shape 2) is an OCCASIONAL option, not a co-default, and must never open with "Curious"; use the affirmation/claim shapes sparingly, since leaning on them is what creates the repetitive, templated feel:
1. Observation on one specific detail, then one plain thought.
2. A genuine question (open, invites the author to say more) — occasional only, and led by the real question word, never "Curious".
3. Plain human affirmation of the core idea, sometimes ending with the author's name.
4. Safe human observation when the topic is too technical ("not many people talk about this side of...").
5. Acknowledgement of the work for highly technical posts ("interesting read, thanks for sharing this publication").

BEFORE RETURNING, run these tests and rewrite if it fails any:
- Structure test: is it the nominalized-insight formula? Say it plainly instead.
- Specificity test: could it sit under any post in the niche? Name something specific.
- Spoken test: read it aloud. If it reads written, rewrite it plainer.
=== END HOUSE STYLE ==="""


STRONG_EXAMPLES = """Target register (post -> strong reply). Match this level, do not copy them:
- "Best things you can do for health: decide once, automate the rest." -> "The fundamentals in health are everything, Bryan. Automating the boring stuff is how consistency actually happens."
- "What if one of the most powerful cardiovascular interventions is love?" -> "Good friends and love keep the heart healthy, Francesco. We really underestimate how deeply relationships affect the body."
- "Western Switzerland to introduce a four-day workweek." -> "Four-day workweeks sound appealing, as long as it doesn't turn into pressure to deliver the same work in four days instead of five. Curious how they handle that part."
- "The next big thing in longevity won't be better data, it'll be behavioral change." -> "Numbers don't change behavior. Meaning does. And meaning needs context, continuity, and a relationship, not a dashboard."
- "Most people with low Vitamin D don't feel symptoms." -> "Good reminder about Vitamin D year-round, Dan. Easy thing to overlook heading into winter."
"""


# --- Benchmark: programmatic slop check -------------------------------------

_BANNED_SUBSTRINGS = [
    # seven slop patterns + craft evaluation
    "resonates deeply", "find myself nodding", "hit home", "articulated this beautifully",
    "the way you've framed", "the way you framed", "your observation about",
    "fresh and spot-on", "thoughtful and timely", "refreshing and impactful",
    "essential topic", "crucial point", "vital perspective",
    "rare to see", "so refreshing", "it's not often", "not often you see",
    "valuable insights", "appreciate the inspiration", "thought-provoking",
    "powerful reminder", "serves as a reminder", "important reminder", "great reminder",
    # filler / summary / confirming
    "what stood out", "you make a great point", "couldn't agree more",
    "worth sitting with", "worth watching", "the heart of this",
    "it's worth noting", "in today's world", "delve", "tapestry", "testament",
]

_PRAISE_OPENERS = [
    "great post", "great point", "love this", "interesting take", "insightful",
    "absolutely", "it's true that", "so important", "so true", "well said",
    "thanks for these", "excellent post", "what a", "such a",
]

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF❤]"
)

# Over-certainty / false precision — science should read nuanced, not black-and-white
# (per Lara: e.g. "that explains it almost exactly" is too certain).
_OVERCERTAIN_RE = re.compile(
    r"\b(almost exactly|exactly explains|explains (it|that|this)[^.]{0,25}exactly|"
    r"matches[^.]{0,30}exactly|lines up[^.]{0,20}exactly|proves|proven|scientifically proven|"
    r"definitely|guarantees?|guaranteed|always works|in every case|without a doubt|no question that)\b"
)


def _sentence_count(text: str) -> int:
    parts = [p for p in re.split(r"[.!?]+", text) if p.strip()]
    return len(parts)


# Negation-as-a-device — the "it's not X, it's Y" family. Hard-banned everywhere.
_NEG_DEVICE_RES = [
    re.compile(r"\bit'?s not\b[^.]{0,60}\bit'?s\b"),
    re.compile(r"\b(that|this|it) is not\b[^.]{0,90}\.\s*(it|that|this) is\b"),
    re.compile(r"\bis not\b[^.]{0,70},\s*(it'?s|it is|but|rather)\b"),
    re.compile(r"\bisn'?t\b[^.]{0,70}\b(it'?s|it is)\b"),
    re.compile(r"\bnot just\b[^.]{0,60}\bbut\b"),
    re.compile(r"\bnot only\b[^.]{0,70}\bbut\b"),
    re.compile(r"\bnot about\b[^.]{0,60}\babout\b"),
    re.compile(r",\s*not\s+(a|an|the|just|about|because)\b"),
]


def has_negation_device(text: str) -> bool:
    """True if the text uses negation as a rhetorical device (define-by-what-it-isn't)."""
    low = (text or "").lower()
    return any(r.search(low) for r in _NEG_DEVICE_RES)


# The over-used "biomarkers shift before symptoms" template — the #1 repetition tell.
_FORMULA_RES = [
    re.compile(r"\b(show|shows|showing|shows up|show up|appear|appears|surfaces?|emerges?|begins?|starts?)\b[^.]{0,55}\bbefore\b[^.]{0,55}(symptom|diagnos|scan|blood ?work|panel|label|warning|a test|clinic|shows up)", re.I),
    re.compile(r"\b(decades?|years?|months?|weeks?|well|long)\s+before\b", re.I),
    re.compile(r"\btends?\s+to\s+show\s+up\b", re.I),
    re.compile(r"\bshows?\s+up\b[^.]{0,40}\bbefore\b", re.I),
    re.compile(r"\bbefore\b[^.]{0,30}\b(shows? up|appears?|it (shows|hits|lands))\b", re.I),
]


def has_formula(text: str) -> bool:
    """True if the draft uses the massively over-used 'X shows up before symptoms/diagnosis/scan'
    construction (or 'tends to show up') — the dominant repetition pattern reviewers flagged."""
    return any(r.search(text or "") for r in _FORMULA_RES)


def check_violations(text: str) -> list[str]:
    """Return a list of house-style violations in a draft. Empty list = clean."""
    t = (text or "").strip()
    low = t.lower()
    v = []
    if "—" in t or "–" in t:
        v.append("em dash")
    if "!" in t:
        v.append("exclamation point")
    if _EMOJI_RE.search(t):
        v.append("emoji")
    if _sentence_count(t) > 2:
        v.append(f"too long ({_sentence_count(t)} sentences; aim for 1-2)")
    if len(re.findall(r"[A-Za-z']+", t)) > 40:
        v.append(f"too wordy ({len(re.findall(r'[A-Za-z]+', t))} words; aim ~15-25)")
    if has_formula(t):
        v.append("over-used 'shows up before symptoms/diagnosis' template (repetition)")
    if re.search(r"\b(tends?|seems?)\s+to\b", low):
        v.append("hedge tic ('tends to'/'seems to') — state it plainly or vary it")
    if has_negation_device(t) or re.search(r"\bnot just\b", low):
        v.append("negation-as-device (say what it is, not what it isn't)")
    # nominalized-insight formula: [the/this/that + abstract noun] + is + [meta-claim about
    # what most/others miss]. Kept within one sentence ([^.]) and gated on a real meta-claim
    # marker so plain "the X is how Y happens" sentences don't trip it.
    if (
        re.search(r"\b(the|this|that|these|those)\b[^.]{3,70}\bis (the|a|an|one|what|where|something|how|why)\b[^.]{0,70}(most|don'?t|few|still|would|wouldn'?t|no one|nobody|rarely|hardly|isn'?t)\b", low)
        # the classic nominalizing openers from V2 — these + between/of/from + "is" are the tell.
        or re.search(r"\b(gap|distinction|shift|tension) (between|of|from)\b[^.]{0,60}\bis\b", low)
    ):
        v.append("nominalized-insight structure")
    if _OVERCERTAIN_RE.search(low):
        v.append("over-certainty (too black-and-white; science should read nuanced)")
    for opener in _PRAISE_OPENERS:
        if low.startswith(opener):
            v.append(f"praise opener: '{opener}'")
            break
    for phrase in _BANNED_SUBSTRINGS:
        if phrase in low:
            v.append(f"banned phrase: '{phrase}'")
    return v
