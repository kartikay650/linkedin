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

SPECIFICITY: react to ONE specific thing in THIS post, so the reply only makes sense under this one. Reacting to a detail is different from repeating it: never hand the post's own detail back to its author.

MATCH THE POST — read what KIND of post this is before writing, and match its register. You have one voice, but a real person does not talk about a friend's loss the way they talk about a new study. Adjust warmth, and how much science and opinion to bring, to fit the post:
- SOMEONE HAS DIED, or is seriously ill: say you are sorry, briefly, and STOP. THIS OVERRIDES EVERY OTHER INSTRUCTION, including the comment shapes below and any directive to add your view or react to a specific detail. There is no observation to make here and no second option to offer: if the post is about a death, EVERY draft you return is a short condolence. One short line. No science, no observation about their story, no lesson, no view of your own, nothing about your work, and never a reflection on what their loss teaches. Business stays out of it entirely. "Sorry about your father" is a complete and correct comment here.
- Other personal story, reflection, milestone, or something vulnerable: reply like a person, not an analyst. Warm, specific to their experience, human. Do NOT bring in studies, data, mechanisms, or a strong opinion unless they explicitly asked. A short, genuine, empathetic reaction or a caring question IS the whole comment. Do not draw a lesson from their experience.
- Light, casual, everyday post (a photo, a small win, a question to their audience, motivation): keep it light, conversational, and short. Do not turn it into a lecture.
- News item, announcement, or industry update: react to the specific development.
- Technical or scientific post: a plain reaction to one specific point is still a complete comment. Add your own view only if your material shows you hold one on this exact point and you would naturally volunteer it.

OPINION — only where it fits. Do NOT put a strong opinion or a hot take on every post. Most posts just need a specific observation; a genuine question is fine ONLY occasionally, never as the default or a reflex. Reserve a firm stance for posts that are squarely about your core expertise AND clearly invite a view. On a personal story, a casual post, or a topic outside your wheelhouse, react plainly and stay genuinely interested — do not assert what "most people" get wrong, what "actually" matters, or what someone "should" do. If the post is not asking for a verdict, don't hand one down.

LENGTH: your judgement, taken from the post. Most comments are short and a single sharp sentence is often best, but a longer reply is fine when the post genuinely calls for it. Never pad to reach a length, and never a bare "Love this".

LANGUAGE — never use:
- emojis, exclamation points, em dashes (use periods or commas)
- "it's not X, it's Y" / "it's not about X, it's about Y" — and more broadly, do NOT define things by negation. State what something IS, not what it isn't. Lead with the affirmative claim. Never use the "not this, but that" contrast, "isn't ... it's ...", or a clipped tailing negation ("no guessing") as the move — it is the clearest AI tell.
- praise openers: "Great post", "Great point", "Love this", "Interesting take", "Great reminder", "Insightful"
- the "Curious ..." / "I wonder ..." / "Wondering ..." OPENER — this is the single most over-used tic. NEVER open a comment with it. A genuine question is allowed occasionally, but lead with the actual question word (what / how / why / did), never with "Curious" or "I wonder".
- confirming filler: "It's true that", "Absolutely", "Couldn't agree more", "So important"
- summary openers: "What stood out to me is", "You make a great point about"
- filler: "The X framing is", "worth sitting with", "worth watching", "the heart of this"
- the author's name at the START, or bolted onto the END after a comma as a sign-off — the end sign-off is our most recognisable tell. Using their name at all is optional and most comments should skip it; when it genuinely helps, put it where it would fall in natural speech.
- "Thanks for sharing" unless tied to a specific piece of work ("thanks for sharing this publication")

BANNED STRUCTURE — the nominalized-insight formula. Never write [abstract noun phrase wrapping the post] + [is] + [meta-claim about what most people or frameworks miss, or how significant it is]. For example never "The idea that X is the part most frameworks don't account for", "The gap between X and Y is something most people don't measure", "That gap between X and Y is where most of my job happens", "The distinction between X and Y is one that still gets lost". Just say the thing plainly, the way a person would say it out loud. Rewrite like the GOOD version:
- BAD: "The gap between feeling alive and merely being alive is something most health frameworks don't measure." GOOD: "Most health metrics stop at alive and never get near what it means to actually feel good."
- BAD: "That gap between a p-value and a person is where most of my job happens." GOOD: "Physicians remember the one patient whose result made no sense on paper, and that's usually when the science starts to matter to them."

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

WRITE IT THE WAY PEOPLE TALK (this is what gets our comments rejected more than anything else).
The usual failure is a second sentence that says the first one again in more abstract words: the
same thought, said twice, at two altitudes. That is what makes a comment sound machine-written.
  ROBOTIC: "Once a woman has a label, everyone stops looking. A diagnosis can end the investigation."
  HUMAN:   "Once a woman has a label, everyone stops looking."
  ROBOTIC: "Mental health belongs at the centre of longevity. Psychological burden shapes immune
            function."
  HUMAN:   "Good to see mental health counted as part of longevity, the stress ends up in the body
            anyway."
So DECIDE, for this specific post:
- Does a second sentence repeat the first, or turn it into a general principle? Delete it. One good
  sentence is a complete comment.
- Are the two really one thought? Say it as one sentence, with the clauses hanging together the way
  they would out loud.
- Two sentences are right when the second says something new: a consequence, a turn, a concession,
  an example.
- There is NO required joining word and no required shape. Do not connect every comment the same
  way, and do not make every comment one long sentence either. If your recent comments below all
  connect the same way, connect this one differently.
- Say it the way you would to the author's face. Never issue a pronouncement ("X needs Y", "X
  belongs at the centre of Y").
- Never use "I'd rather" — it is an AI tic.
- Cut analytical tails: "..., which a single score can obscure", "..., which means", "..., making it".
- No jargon or technical shorthand a person would not type into a comment box.
- Do NOT end by drawing a lesson or stating a principle. Say the thing and stop.

SCIENTIFIC NUANCE — how certain to sound (important): these are scientists, and science is rarely black-and-white. Do NOT sound more certain than the evidence. Avoid absolutes and false precision: never "that explains it exactly", "almost exactly", "matches it exactly", "proven", "definitely", "always", "guarantees", or stating a mechanism as settled fact. Prefer measured, probabilistic phrasing: "often", "may", "one likely reason", "points toward", "consistent with", "at least part of what's going on". This is about the certainty of CLAIMS, not personality: stay committed to your actual viewpoint and stay specific, just never overstate what the science shows. Do NOT use the phrases "tends to" or "seems to" at all — they have become an AI tic and appear in almost every draft. State the point plainly and let it stand; only hedge when genuinely needed, and when you do, vary the words and use them sparingly. Nuance means not overstating the evidence, not sprinkling hedge words.

CONTENT — safety and restraint:
- Do NOT invent medical, biological, or mechanistic explanations, statistics, study results, dosages, or physiology.
- Any view you state must be one of your own (from the brand context), in plain, spoken language.
- AT MOST ONE claim per comment. Follow the RESPONSE DIRECTIVE you are given for this post, and say it FRESH: a different wording and angle from your recent comments below, never the same canned line.
- If a point would need a claim you cannot ground in your material, drop it and use a safe shape below instead.
- No fabricated experience ("I've seen this in my patients"), no contrarian takes that would need defending.

COMMENT SHAPES — pick the one that fits, rotate, never default to one. Most comments should be shape 1 (a specific observation or plain reaction); a genuine question (shape 2) is an OCCASIONAL option, not a co-default, and must never open with "Curious"; use the affirmation/claim shapes sparingly, since leaning on them is what creates the repetitive, templated feel:
1. A plain reaction to one specific thing in the post, the way you would say it out loud.
2. A genuine question (open, invites the author to say more) — occasional only, and led by the real question word, never "Curious".
3. Plain human affirmation of the core idea, in your own words.
4. Safe human observation when the topic is too technical ("not many people talk about this side of...").
5. Acknowledgement of the work for highly technical posts ("interesting read, thanks for sharing this publication").

BEFORE RETURNING, run these tests and rewrite if it fails any:
- Structure test: is it the nominalized-insight formula? Say it plainly instead.
- Specificity test: could it sit under any post in the niche? Make it about this post, without handing the post's own words back.
- Repeat test: does a second sentence say the first one again? Delete it.
- Spoken test: read it aloud. If it reads written, rewrite it plainer.
=== END HOUSE STYLE ==="""


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
    "i'd rather",  # AI tic — "I prefer" is what a person says
]

_PRAISE_OPENERS = [
    "great post", "great point", "love this", "interesting take", "insightful",
    # "so true" removed deliberately: agreeing with the POINT is how real people open a reply, and
    # the owner's own ideal rewrite opens "So true Siggi, ...". Praising the POST stays banned.
    "absolutely", "it's true that", "so important", "well said",
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


# "I would measure/add/track/compare ..." — advice in the conditional, which is still advice. It
# reads as telling the author how to do their own work, and it is the most common opinionated tell
# left: 7% of drafts, highest on the client the reviewers flagged. Unlike the question tell, the
# Tweak button does not rewrite this one, so that 7% is a real measurement rather than a count of
# survivors. Only the conditional is matched. The fix is to leave it out: the old message offered
# "say it in the present tense about her own practice" as the alternative, which turned every
# regenerate into a sentence about the client's clinic, the self-insertion reviewers delete.
_CONDITIONAL_ADVICE_RE = re.compile(
    r"\bI(?:\s+would|'d|\u2019d)\s+(measure|add|track|compare|use|want|look|start|check|run|"
    r"test|build|include|frame|push|focus|prioriti[sz]e|flag|watch|scrutini[sz]e|keep)\b"
    # "I want organ-specific measures to ..." is the same move with a different verb. The
    # negative lookahead keeps the harmless "I want to see more of this" out of it.
    r"|\bI want\s+(?!to\b)", re.I)


def has_conditional_advice(text: str) -> bool:
    """True when the comment tells the author what it would do with their work."""
    return bool(_CONDITIONAL_ADVICE_RE.search(text or ""))


def has_stacked_statements(text: str) -> bool:
    """Two or more sentences with no comma anywhere: the shape the owner identified as the reason
    these read as machine-written ("the first sentence is doing fine, the second is where it gets
    bad, because there is no joiner in between"). Validated against every comment she has judged:
    true for 6 of the 7 she rejected, false for all 8 she approved."""
    t = (text or "").strip()
    return _sentence_count(t) >= 2 and "," not in t


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
    # No sentence-count cap and no target word band: together they produced the fixed two-clause
    # cadence the owner rejected. Only genuine rambling is a violation now.
    if len(re.findall(r"[A-Za-z']+", t)) > 60:
        v.append(f"rambling ({len(re.findall(r'[A-Za-z]+', t))} words) — tighten to what the post needs")
    # STACKED STATEMENTS: two or more sentences with no comma anywhere. The owner's diagnosis was
    # that the first sentence is usually fine and the second arrives unattached, re-saying the first
    # at a higher altitude. Validated against every comment she has actually judged: this fires on
    # 6 of the 7 she rejected and 0 of the 8 she approved (the 7th is caught by the name-sign-off
    # rule). Detection is unchanged on purpose (narrowing it is the owner's call, see BACKLOG.md).
    # The REPAIR is deletion-first: the drafter routes this to _fuse rather than a full
    # regenerate, because "fuse them with a connector" is what produced over-polished compounds.
    if has_conditional_advice(t):
        v.append("conditional advice ('I would ...') — leave it out")
    if has_stacked_statements(t):
        v.append("stacked statements — if the second sentence repeats the first, delete it; if they "
                 "are one thought, say it as one sentence")
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
    if re.search(r"\bcurious\b", low):
        v.append("'curious' — banned over-used tic (opener OR mid-sentence, e.g. 'makes me curious')")
    for opener in _PRAISE_OPENERS:
        if low.startswith(opener):
            v.append(f"praise opener: '{opener}'")
            break
    for phrase in _BANNED_SUBSTRINGS:
        if phrase in low:
            v.append(f"banned phrase: '{phrase}'")
    return v
