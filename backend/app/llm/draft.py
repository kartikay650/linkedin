import re
from concurrent.futures import ThreadPoolExecutor

from app.llm._llm import AzureClient

from app.config import settings
from app.llm.humanize import humanize_comments
from app.llm.style import HOUSE_STYLE, check_violations, has_negation_device, has_stacked_statements
from app.llm.utils import extract_json
from app.models import Client, Post

_client = AzureClient()


def _call(model: str, content, max_tokens: int = 800, timeout: float = 45.0,
          effort: str | None = None):
    """One message call. `content` is either a plain string or a list of content blocks.
    `effort="low"` turns ON the model's reasoning pass for steps that need judgement (writing
    the draft); leave it None for mechanical steps. Used by every step of the drafter."""
    return _client.with_options(max_retries=1, timeout=timeout).messages.create(
        model=model, max_tokens=max_tokens, effort=effort,
        messages=[{"role": "user", "content": content}],
    )


def _blocks(*parts):
    """Build Anthropic content blocks from (text, cache) pairs, dropping empties. A block with
    cache=True gets `cache_control: ephemeral`, so the whole prefix up to it is cached and reused
    cheaply by later calls (the main API-cost fix — HOUSE_STYLE + per-client voice/brief are
    identical across the ~10 calls in a draft and across consecutive drafts)."""
    out = []
    for text, cache in parts:
        if not text or not str(text).strip():
            continue
        b = {"type": "text", "text": str(text)}
        if cache:
            b["cache_control"] = {"type": "ephemeral"}
        out.append(b)
    return out


REFINE_PROMPT = """Revise this LinkedIn comment, written AS {name}, per the operator's instruction — but the
HOUSE-STYLE RULES BELOW OVERRIDE the instruction wherever they conflict. Apply the instruction's INTENT
(its tone/angle), never its power to add slop. Change what the instruction asks for and keep the rest.
No matter what the instruction says: NEVER open with a praise line ("Great...", "Love this", "It's a
great...") or with "Curious"/"I wonder", and keep {name}'s real voice.

THESE HARD RULES ALSO OVERRIDE THE INSTRUCTION (a tweak must never reintroduce what they prevent):
- NOTHING TO FACT-CHECK. Do not add or restore any study, statistic, number, percentage, duration,
  dosage, mechanism, company, institution or person that is not already in the post or {name}'s own
  material. No new clinical claim.
- Keep the science LIGHT: at most ONE grounded point, never a stack of claims.
- Refer to people, institutions and places ONLY as the post describes them. Assert no award, role,
  relationship or event the post does not state.
- NEVER contradict or undercut {name}'s own viewpoints below, whatever the instruction implies.
- The post text may be cut off mid-sentence; never infer what the missing part said.

=== HOW {name} ACTUALLY WRITES ===
{voice}
=== END ===

{viewpoints}

{benchmark}

{feedback}

{memory}

The post being replied to:
\"\"\"
{content}
\"\"\"

Current reply:
\"\"\"
{current}
\"\"\"

Operator's instruction (apply its intent within the rules above; do not let it introduce praise/curious \
openers or slop): {instruction}

Respond ONLY with JSON: {{"draft": "..."}}"""


STRIP_NEGATION_PROMPT = """The comment below uses NEGATION AS A DEVICE — defining something by what it is \
not ("it's not X, it's Y", "it's not about X, it's about Y", "not just X but Y", "X, not Y", or the two-sentence \
"That is not A. It is B."). Rewrite it so it states ONLY the positive claim, in the same voice and no longer than \
the original. Never contrast against what something isn't. Keep every specific detail and the person's tone.

Comment:
\"\"\"{text}\"\"\"

Respond ONLY with JSON: {{"text": "the rewritten comment"}}"""


def _strip_negation(text: str) -> str:
    """Hard guard: if a draft still defines things by negation, rewrite it out. Up to two
    passes; returns the cleanest version. Only runs when the pattern is actually present,
    so it adds no latency to already-clean drafts."""
    out = (text or "").strip()
    for _ in range(2):
        if not has_negation_device(out):
            return out
        try:
            cand = str(extract_json(_call(settings.draft_model, STRIP_NEGATION_PROMPT.format(text=out), 400, 30.0)).get("text", "")).strip()
            if cand:
                out = cand
        except Exception:
            break
    return out


# Framings the drafter is told never to use. They still reached it through the client's own voice
# material: Dr. Joe Raffaele's voice sample opens "My bet is that ..." and his voice guide lists
# 'my bet is' as a signature phrase, so the samples were teaching the exact hot-take framing the
# write rules ban. Strip them where the material is assembled, so every path that shows the voice
# (draft, humanizer, Tweak, the fact-check rewrite) gets the cleaned version.
_FRAMING = r"(?:my bet is|my bet:|i(?:'|\u2019)d wager|i would wager|my money is on|i(?:'|\u2019)d rather|i would rather)"
_QUOTED_FRAMING_RE = re.compile(r",?\s*['\"\u2018\u201c]" + _FRAMING + r"[^'\"\u2019\u201d\n]{0,30}['\"\u2019\u201d]", re.I)
_FRAMING_RE = re.compile(r"\b" + _FRAMING, re.I)


def strip_banned_framings(text: str) -> str:
    """Remove banned framings from a client's own material.

    A quoted mention in a description ("uses 'I generally prefer,' 'my bet is'") loses just the
    quoted phrase. A sentence that USES the framing is dropped whole, since cutting the phrase out
    of the middle of a real sentence would leave a sentence the client never wrote."""
    if not text or not _FRAMING_RE.search(text):
        return text or ""
    out_lines = []
    for line in text.splitlines():
        line = _QUOTED_FRAMING_RE.sub("", line)
        if _FRAMING_RE.search(line):
            kept = [x for x in re.split(r"(?<=[.!?])\s+", line) if not _FRAMING_RE.search(x)]
            line = " ".join(kept)
            if not line.strip():
                continue
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def _voice_block(client: Client) -> str:
    """The person's real voice: verbatim samples first (strongest signal), then the
    written description. Falls back to the legacy tone_profile."""
    parts = []
    samples = strip_banned_framings((client.voice_samples or "").strip())
    if samples:
        # If any sample is transcribed speech (podcast/interview/video), it is the best register
        # anchor we have — it is literally how this person talks, which is the target.
        raw = samples
        spoken = any(k in raw.lower() for k in ("podcast", "interview", "spoken", "video"))
        head = ("Verbatim examples of their own words. Some of these are transcribed SPEECH — those "
                "are the truest guide to how they actually talk, so match that rhythm above all:\n"
                if spoken else "Verbatim examples of their own words:\n")
        parts.append(head + raw)
    guide = strip_banned_framings((client.voice_guide or client.tone_profile or "").strip())
    if guide:
        # This text was extracted by brand onboarding from the client's OWN POSTS, and it was
        # being handed to the comment drafter as if it described comments. For Dr. Joe Raffaele it
        # says "uses rhetorical questions to open sections", "closes posts with ... an engaging
        # question to the audience", and lists "my bet is" as one of his signature phrases — which
        # is precisely the question rate and the hot-take framing the reviewer complained about.
        # Four of nine clients carry rhetorical-question guidance, three carry post-closing CTAs.
        # Take the VOICE from it; the post architecture does not transfer to a reply.
        parts.append(
            "How they write THEIR OWN POSTS. Take the voice from this — word choice, register, how "
            "blunt or measured they are, what they care about. Do NOT take the POST ARCHITECTURE: "
            "a comment under someone else's post has no opening hook, no rhetorical question to "
            "open with, no sections, no bullets, no closing call to action and no sign-off. Where "
            "anything here conflicts with the comment rules above, the comment rules win.\n" + guide)
    return "\n\n".join(parts) if parts else "Direct, plain, specific. No fluff."


def _benchmark_block(client: Client) -> str:
    """Operator-curated ideal / non-ideal examples for THIS client (few-shot anchor).

    These had stopped reaching first drafts entirely (dropped in Aug 2026), so Lara Hemeryck's
    hand-picked GOOD/AVOID lines only shaped a Tweak. They are the one source of examples a human
    chose on purpose, so they go back into the per-client block. "Match this tone exactly" is gone:
    told to match ten short lines exactly, the model copies their shape onto every post."""
    ex = (getattr(client, "benchmark_examples", "") or "").strip()
    if not ex:
        return ""
    return (
        "=== EXAMPLES THE AGENCY PICKED FOR THIS CLIENT (GOOD = how they sound, AVOID = what not to write) ===\n"
        "Take the voice and register from the GOOD lines. Do not copy their wording or their shape; "
        "each post sets its own.\n"
        + ex
        + "\n=== END ==="
    )


# A note this long is a pasted prompt or a post summary, not a correction. Real corrections in the
# history are one or two lines ("I always see 'in the kids I treat' in most of the comments").
_FEEDBACK_NOTE_MAX = 400


def _feedback_block(client: Client) -> str:
    """Recent corrections a reviewer gave for this client.

    This block once carried 92 copies of one pasted ChatGPT prompt — "Write a 3-sentence comment
    ... Sentence 1: a strong reaction ... Sentence 2: explain ... Sentence 3: a supportive closing"
    — for four clients, under the heading "apply every one". It filled all five slots, pushed the
    one real correction out of the window, and was the literal source of the reaction ->
    explanation -> closing shape reviewers kept rejecting. So: dedupe, cap each note, and frame
    the notes as corrections that apply where relevant, never as a template that sets length or
    structure. The rows themselves were removed on 3 Nov 2026 (backup kept)."""
    notes = getattr(client, "feedback", None) or []
    seen, lines = set(), []
    for n in sorted(notes, key=lambda f: f.id, reverse=True):
        text = " ".join((n.note or "").split())
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        if len(text) > _FEEDBACK_NOTE_MAX:
            text = text[:_FEEDBACK_NOTE_MAX].rsplit(" ", 1)[0] + " ..."
        lines.append(f"- {text}")
        if len(lines) == 5:
            break
    if not lines:
        return ""
    return (
        "=== CORRECTIONS A REVIEWER GAVE FOR THIS CLIENT ===\n"
        "Apply each one only where it is relevant to this post. They say what to avoid or fix; none "
        "of them is a template, and none sets a length or a sentence structure.\n"
        + "\n".join(lines)
        + "\n=== END ==="
    )


def _voice_examples_block(texts: list[str] | None) -> str:
    """Comments a human on the team edited and then approved/posted for THIS client. The route
    picks them (see _approved_examples in routers/posts.py) so that the tool never learns from its
    own unedited output. Voice only: no structure, length or phrasing is to be copied."""
    ex = [t.strip() for t in (texts or []) if t and t.strip()][:5]
    if not ex:
        return ""
    lines = "\n".join(f"- {t}" for t in ex)
    return (
        "=== COMMENTS THE TEAM EDITED AND POSTED FOR THIS CLIENT ===\n"
        "Learn the voice from these: tone, word choice, bluntness. Do NOT copy their structure, "
        "their length or their phrasings; each post sets its own.\n" + lines + "\n=== END ==="
    )


def _avoid_block(avoid_texts: list[str] | None) -> str:
    """Show the client's recent comments so the model writes something structurally
    different — the core fix for the 'every comment sounds the same' repetition."""
    texts = [t.strip() for t in (avoid_texts or []) if t and t.strip()][:12]
    if not texts:
        return ""
    lines = "\n".join(f"- {t}" for t in texts)
    return (
        "=== RECENT COMMENTS ALREADY WRITTEN FOR THIS CLIENT — do NOT sound like these ===\n"
        "Your reply must be clearly different from every one below: a different opening word, a "
        "different sentence shape, a different angle. Do not reuse their phrasings.\n" + lines + "\n=== END ==="
    )


def _siblings_block(texts: list[str] | None, name: str) -> str:
    """Comments OTHER profiles already made on this SAME post, so two profiles never post the same
    comment. It used to demand "a genuinely different angle, grounded in HER own expertise", and
    since it fires on most posts it was one of the main sources of forced expertise. A different
    DETAIL of the post is enough to tell two comments apart."""
    ex = [t.strip() for t in (texts or []) if t and t.strip()][:8]
    if not ex:
        return ""
    lines = "\n".join(f"- {t}" for t in ex)
    return (
        "=== OTHER PROFILES ALREADY COMMENTED ON THIS EXACT POST ===\n"
        f"These were written for OTHER people on this same post. {name}'s comment must react to a "
        "different detail of the post, in different words. Do not reword these or make their point:\n"
        + lines + "\n=== END ==="
    )


def _opener(text: str) -> str:
    return " ".join(re.findall(r"[a-z']+", (text or "").lower())[:3])


def _first_word(text: str) -> str:
    w = re.findall(r"[a-z']+", (text or "").lower())
    return w[0] if w else ""


# A comment "asks the author something" — a literal '?' OR the soft-question forms
# ("Curious what...", "I wonder if...") that read as statements but function as questions.
_SOFT_Q_RE = re.compile(r"\bcurious\b|\bwonder(ing)?\b|\bi'?d love to (know|hear)\b", re.I)


def _is_question(text: str) -> bool:
    t = (text or "").strip()
    return t.endswith("?") or bool(_SOFT_Q_RE.search(t))


# The single most persistent tic — the "Curious ..." / "I wonder ..." OPENER. Banned as a STANDING
# rule (not only when it's currently over-used), because a purely adaptive suppressor is self-
# releasing: once the rate drops it switches off and the tic drifts back. A genuine question is
# still fine — it just can't open this way.
_CURIOUS_OPENER_RE = re.compile(r"^\s*(curious\b|wondering\b|i\s+wonder\b|i'?d\s+love\s+to\s+(know|hear)\b)", re.I)


def _opens_curious(text: str) -> bool:
    return bool(_CURIOUS_OPENER_RE.match(text or ""))


def output_profile(texts: list[str] | None) -> dict | None:
    """The tool's recent OUTPUT signature, so a new draft can steer away from whatever shape
    it has been OVER-using lately — adaptive anti-repetition, not a fixed ban list. Computed
    over recent comments for this client PLUS a global sample across all clients (so a tic
    that spreads across clients, like the 'Curious ...?' question, is caught). Returns None
    when there's too little history to judge."""
    from collections import Counter
    seen: list[str] = []
    for t in (texts or []):
        t = (t or "").strip()
        if t and t not in seen:
            seen.append(t)
    n = len(seen)
    if n < 5:
        return None
    openers = Counter(w for w in (_first_word(t) for t in seen) if w)
    q = sum(1 for t in seen if _is_question(t))
    cur = sum(1 for t in seen if "curious" in t.lower())
    threshold = max(2, round(n * 0.15))  # an opener used in >=15% of recent comments is over-used
    overused = sorted(w for w, c in openers.items() if c >= threshold)
    return {"n": n, "q_rate": q / n, "curious_rate": cur / n, "overused_openers": overused}


def _self_awareness_block(profile: dict | None) -> str:
    """Feed the tool its own recent pattern stats and tell it to break them — the 'it knows
    what it has already said' loop. Adaptive: it targets whatever is currently over-used, so
    no new hardcoded phrase ban is needed as tics shift over time."""
    if not profile:
        return ""
    rules = []
    if profile["curious_rate"] >= 0.06:
        rules.append("- Do NOT use the word 'Curious', and do not open by saying you are curious.")
    if profile["q_rate"] >= 0.12:
        rules.append("- Do NOT ask the author a question this time. Make a plain statement or observation.")
    if profile["overused_openers"]:
        rules.append("- Do NOT open with any of these over-used words: "
                     + ", ".join(f"'{w}'" for w in profile["overused_openers"]) + ".")
    if not rules:
        return ""
    header = (
        f"SELF-CHECK — across your last {profile['n']} comments (this client + others), "
        f"{round(100*profile['q_rate'])}% asked the author a question and "
        f"{round(100*profile['curious_rate'])}% used the word 'Curious'. You are repeating yourself. "
        "Break the pattern this time:"
    )
    return "=== BREAK YOUR OWN PATTERN ===\n" + header + "\n" + "\n".join(rules) + "\n=== END ==="


def _draft_problems(text: str, avoid_texts: list[str] | None, profile: dict | None = None) -> list[str]:
    """Deterministic quality gate: house-style violations (incl. the over-used template,
    length, negation, slop), reusing a recent comment's opening, and — adaptively — matching
    whatever pattern the tool is currently over-using (per `profile`)."""
    problems = list(check_violations(text))
    op = _opener(text)
    if op and any(op == _opener(t) for t in (avoid_texts or [])):
        problems.append("same opening as a recent comment")
    if _opens_curious(text):  # STANDING (always-on) — the persistent tic, not gated on the rate
        problems.append("opens with 'Curious'/'I wonder' — a banned over-used opener")
    if profile:
        fw = _first_word(text)
        low = (text or "").lower()
        if fw and fw in profile["overused_openers"]:
            problems.append(f"opens with the over-used word '{fw}'")
        if profile["curious_rate"] >= 0.06 and "curious" in low:
            problems.append("uses 'Curious', which is over-used right now")
        if profile["q_rate"] >= 0.12 and _is_question(text):
            problems.append("is a question, and questions are over-used right now")
    return problems


# --- Reasoning drafter -------------------------------------------------------
# Instead of hand-coded heuristics deciding what to say, the model REASONS per-post about how
# the post should be answered — engage a real argument (even under a personal/novelty hook) vs
# honour a genuinely human moment — grounds any substance in the client's OWN material (so it's
# never invented), drafts to that plan, and self-critiques against it. The self-aware
# anti-repetition memory, humanizer, negation strip, and violation/length guardrails all still
# run around it. See the "reasoning, not a flag" design (2026-08).

_BRIEF_PROMPT = """Summarise what {name} believes and works on, as BACKGROUND for someone writing LinkedIn \
comments in their name. Use ONLY the material below — NEVER invent facts, studies, numbers, or positions they have \
not expressed. If it is not in the material, leave it out.
This is background so the writer never contradicts them or claims a view they do not hold. It is NOT a list of \
points to put into comments, so do not phrase anything as a line to use.
{material}
Return 6-10 short bullet lines: their main positions and the subjects they work on. Plain language, no preamble."""


def _expertise_brief(client: Client) -> str:
    """Background on what the client believes and works on, distilled ONLY from their own material
    (viewpoints, key messages, audience, voice samples, guardrails), so the drafter never invents a
    position or contradicts one. Generated on the fly on the fast model and reused across this
    post's candidates.

    It used to be "the specific points she can credibly make" and included approved comments, which
    turned it into a list of lines to insert: the comment tool kept bringing the client's expertise
    to posts that did not need it. Approved comments are left out now; the drafter already sees the
    edited ones in their own block."""
    mats = []
    for label, val in (
        ("VIEWPOINTS", client.viewpoints), ("KEY MESSAGES", client.key_messages),
        ("AUDIENCE", client.audience), ("THEIR OWN WORDS", strip_banned_framings(client.voice_samples or "")),
        ("GUARDRAILS", client.guardrails),
    ):
        if (val or "").strip():
            mats.append(f"{label}: {val.strip()[:2000]}")
    if not mats:
        return ""
    try:
        return _call(settings.relevance_model, _BRIEF_PROMPT.format(name=client.name, material="\n".join(mats)), 700, 30.0).content[0].text.strip()
    except Exception:
        return ""


def _plan(client: Client, post: Post, brief: str, siblings_block: str = "") -> dict:
    """Tone directive for the drafter. No separate reasoning call: on this model it produced
    cautious, process-y scaffolding that flattened drafts. The generate step judges the post itself.

    The default is what the client would naturally say. It used to be "engage the single most
    important point with ONE specific, grounded point in this person's own voice and expertise",
    which made every post a prompt for expertise, and the reviewers' complaints about forced
    insight, first-person self-insertion and comments that repeat the post all trace back to it.
    The client's own view is still allowed, under three conditions that say when it is NOT."""
    approach = (
        "First decide what this post is. If someone has died or is seriously ill, write a short "
        "condolence and nothing else. If it is another personal or human moment (a milestone, "
        "something vulnerable, a photo, an off-topic post), reply warmly and briefly, with no "
        "science, data or biomarkers. Otherwise, say what you would naturally say to the post, the "
        "way you would say it to the author in person. Bring in a view of your own only when your "
        "material shows you hold it, you would volunteer it on this post, and it is not about your "
        "own clinic, patients, routine or credentials (unless the post asks about them)."
    )
    return {"approach": approach}


def _rules_block(client: Client) -> str:
    """Only the HARD constraints (CTA rules + guardrails) — the knowledge itself lives in the brief.

    CTA rules are reframed rather than dropped. They describe what this person does at the end of
    their OWN posts: DM keywords, booking links, "CTAs should invite engagement (repost, follow,
    answer a question)". All nine clients had that fed in as a hard rule for writing a COMMENT on
    somebody else's post, where a call to action is never appropriate. The prohibitions in there
    are still worth keeping ("do not push consumer product purchases", "do not overstate certainty
    on early-stage findings"), so the block keeps the text and inverts its instruction."""
    parts = []
    if (client.cta_rules or "").strip():
        parts.append(
            "What they do at the end of THEIR OWN POSTS — included only for the prohibitions in "
            "it, which still apply. A comment under someone else's post NEVER carries a call to "
            "action, a DM keyword, a link, a booking prompt, or an invitation to engage, follow, "
            "repost or answer a question. Ignore every instruction here telling you to invite "
            "engagement; obey every one telling you not to do something:\n" + client.cta_rules.strip())
    if (client.guardrails or "").strip():
        parts.append("Guardrails (hard rules):\n" + client.guardrails.strip())
    return ("=== HARD RULES ===\n" + "\n\n".join(parts) + "\n=== END ===") if parts else ""


# The draft prompt is split into three blocks so the static ones get PROMPT-CACHED (big API-cost
# saving — the same HOUSE_STYLE and per-client voice/brief are re-sent on every one of a draft's
# ~10 calls and across drafts). Block 1 = global-static (HOUSE_STYLE + the fixed write rules);
# block 2 = per-client-static (voice, approved examples, rules, feedback, brief); block 3 = the
# per-draft variable part (plan, memory, the post). Only 1 and 2 are cached.
_WRITE_RULES = """=== HOW TO WRITE THIS REPLY ===
You are writing as the client named below: "you" and "your" in these rules mean them. Follow the
RESPONSE DIRECTIVE given below. The default is what you would naturally say to this post.

NOTHING TO FACT-CHECK (hard rule, overrides everything else). No one on the team is a scientist who
can verify a factual claim, so a comment that needs checking is unusable. An opinion of yours is not
a factual claim: it needs no verification, because it is attributed to you. Only three things may
appear in the comment:
1. What the post itself says.
2. What you believe: your viewpoints and key messages, given below. Use one only when the post is
   about it and you would naturally say it; it never needs evidence.
3. Nothing else.
So:
- NEVER introduce a study, statistic, number, percentage, duration, dosage, mechanism, company,
  institution, product or person that is not already in the post or your material.
- No new clinical or statistical claim of your own. If a point would need evidence to stand up,
  drop it and say the plainer thing.
- Keep the science LIGHT: at most ONE grounded point. Do not stack claims. Over-claiming and
  claim-density damage the client's credibility more than a simple comment ever would.

REACT, DO NOT REPEAT. The author already knows what they wrote. Handing one of their facts back,
then adding a general principle ("Prevention starts while people still feel healthy"), is the reply
nobody wants. Say what a colleague would naturally say to it in person. The comment is about their
post, not about you: use "I" only where a person naturally would, and keep your own clinic,
patients, routine and credentials out of it unless the post asks about them.
- A personal story, a loss, a milestone, something vulnerable, or a light everyday post: bring no
  position at all. React like a person. Warmth is the whole comment, and a stance here is intrusive.
- A post in your field: a plain, specific reaction is still the default. Add a view of your own
  only when your material below shows you hold it on this exact point and you would volunteer it
  here.
- A post outside your field: a plain observation about one thing in it is enough. Do not
  manufacture a view you do not hold.
Whatever you say is a colleague's reaction, never a verdict on their work. Banned outright, because
they read as a hot take:
    "My bet is that ...", "I'd wager", "my money is on" — never frame a view as a prediction.
    "I cannot trust it", "I don't trust", "that tells us nothing", "that is useless" — never
    deliver a judgement on someone else's tool, study or method.
    "I would measure ...", "I would add ...", "I would track ...", "I'd compare ..." — advice in
    the conditional is still advice, and it reads as telling the author how to do their work.
    Leave it out.
A firm stance belongs only where the post explicitly asks for one. Never assert a position you
have not stated below.

GET THE POST RIGHT.
- Read what the post actually says before writing. React to its real subject, not the hook.
- The post text may be cut off mid-sentence. If so, only react to what is clearly stated; never
  infer, complete, or guess what the missing part said.
- Refer to people, institutions, universities, companies and places ONLY as the post itself
  describes them. Do not assert any award, role, relationship, affiliation or event that the post
  does not state. If you are not certain who or what something is, do not name it.

NEVER CONTRADICT YOUR OWN VIEWPOINTS (given below). Do not argue the opposite of your stated
philosophy, and do not undercut a position you hold. If the post's topic sits outside your stated
views, stay warm and reactive instead of taking a stance.

BE SPECIFIC TO THIS POST: react to ONE thing the post actually says, so the comment could not sit
under any other post, without repeating it back. BANNED generic filler: "track it over time",
"serial measurements", "careful patient selection", "the confidence it warrants", "broader
clinical/health context", "clinical interpretation", "longitudinal follow-up". Never use "curious"
or "makes me curious".

Let the post set the length, usually short and longer when it earns it. Structurally different from
your recent comments, and never the words "tends to" / "seems to". Respond ONLY with JSON:
{"drafts": ["your one reply"]}"""

_DRAFT_CLIENT = """You are writing ONE LinkedIn comment reply AS {name}. It must be indistinguishable from something {name} typed.

=== HOW {name} ACTUALLY WRITES ===
{voice}
=== END ===

{benchmark}

{voice_examples}

{viewpoints}

{rules}

{feedback}

=== BACKGROUND: WHAT {name} BELIEVES AND WORKS ON ===
So you never contradict {name} or invent a view. These are not points to work into the comment; use
one only when the post is about it.
{brief}
=== END ==="""


def _viewpoints_block(client: Client) -> str:
    """The client's OWN stances, verbatim. Passed raw (not only via the summarised brief) because
    the drafter must never argue against them — a draft that contradicts the client's philosophy
    reads as off-brand even when every fact in it is safe."""
    v = (getattr(client, "viewpoints", "") or "").strip()
    if not v:
        return ""
    return (
        f"=== {client.name}'S OWN VIEWPOINTS (never contradict or undercut these; use one only when "
        "the post is about it) ===\n"
        + v[:2000]
        + "\n=== END ==="
    )

_DRAFT_VARIABLE = """=== HOW TO RESPOND HERE (follow this exactly) ===
{approach}

{memory}

The post {name} is replying to:
Author: {author}
\"\"\"
{content}
\"\"\"
{shape}

=== TWO CHECKS BEFORE YOU RETURN (the last things you read, and the two we get wrong most) ===
1. SAID TWICE? If a second sentence repeats the first in other words, or turns it into a general
   principle, delete it. If the two are really one thought, say it as one sentence the way you would
   out loud. Two sentences are fine when the second says something new.
2. WOULD {name} TYPE THIS, under a colleague's post? Cut any sentence that hands the post's own
   point back, exists to show expertise, or brings in your own clinic or routine when the post did
   not ask. This is NOT an instruction to ask a question. A question is an occasional shape, not
   the way to sound engaged, and most comments should be a statement. If the draft ends in a
   question mark, check that a question is genuinely the best reply to THIS post rather than the
   easy way out."""


def _participant_note(client: Client, post: Post) -> str:
    """Warn the drafter when the CLIENT is named in the post they are replying to.

    own_identities() already stops a client commenting on their own posts, but nothing
    covered the case where somebody else's post is ABOUT them. Live example: Deepti Agarwal
    announced a session with "Dr. Joseph Raffaele, MD, who is five years into using this in real
    patients", and we generated Raffaele himself asking outsiders how to interpret GlycanAge —
    the thing he was being interviewed as the expert on. Matching on surname only, since first
    names collide ("Jo Dalton" in a post is not our client "Dr. Joe Raffaele")."""
    surname = re.sub(r"^(Dr\.?|Prof\.?|Mr\.?|Ms\.?|Mrs\.?)\s+", "", (client.name or "").strip())
    surname = surname.split(" ")[-1] if surname else ""
    body = post.content_snippet or ""
    if len(surname) < 4 or surname.lower() not in body.lower():
        return ""
    return (
        "=== YOU ARE IN THIS POST ===\n"
        f"This post names {client.name}. You are a PARTICIPANT here, not an outside observer. Do "
        "NOT ask a question about your own work, your own results, or a subject you are being "
        "presented as the expert on — it reads as though you have forgotten it is you. Reply as "
        "the person being written about: acknowledge it, add something only you would know from "
        "doing the work, or say what you are looking forward to. Never ask the audience to explain "
        "your own field back to you.\n=== END ==="
    )


def _reason_generate_once(client: Client, post: Post, brief: str, plan: dict,
                          voice_ex_block: str, memory_block: str, shape: str) -> str:
    g_static = HOUSE_STYLE + "\n\n" + _WRITE_RULES
    c_static = _DRAFT_CLIENT.format(
        name=client.name, voice=_voice_block(client), benchmark=_benchmark_block(client),
        voice_examples=voice_ex_block, viewpoints=_viewpoints_block(client),
        rules=_rules_block(client), feedback=_feedback_block(client), brief=(brief or "(none)"),
    )
    part = _participant_note(client, post)
    variable = _DRAFT_VARIABLE.format(
        approach=plan.get("approach", ""), name=client.name,
        memory=memory_block, author=post.author_name, content=post.content_snippet,
        shape=("\n" + shape if shape else "") + (("\n\n" + part) if part else ""),
    )
    # Only the GLOBAL static block is marked cacheable, so the system message is byte-identical on
    # every draft call for every client and the whole ~3.2k-token prefix is served from cache. The
    # per-client block rides in the user message: it changes from client to client anyway, and
    # including it in the system message made the system text differ per client, which dropped the
    # measured cache hit rate to ~0 on the draft calls.
    content = _blocks((g_static, True), (c_static, False), (variable, False))
    try:
        # effort="low": the model reasons about the post before writing. This is the step where
        # comprehension, stance and entity accuracy are won or lost, so it gets the thinking pass.
        drafts = [str(d) for d in extract_json(_call(settings.draft_model, content, 800, 50.0, effort="low"))["drafts"] if str(d).strip()]
    except (ValueError, KeyError):
        return ""
    drafts = humanize_comments(drafts, _voice_block(client))
    drafts = [_strip_negation(d) for d in drafts]  # hard-enforce: no negation-as-a-device
    return drafts[0] if drafts else ""


# The post's OWN topic is pre-diagnosis / early-marker / prevention -> "before diagnosis/symptoms"
# phrasing is ON-TOPIC here, not the banned canned tic. Context-gate the formula check so the
# anti-repetition guardrail stops fighting these clients' actual subject matter (preventive medicine
# is literally "act before symptoms"). The self-aware memory still prevents REPEATED phrasing.
_PREDIAG_RE = re.compile(
    r"\b(diagnos|before symptom|reactive|too late|drift|marker|intervene|prevent|early detection|screen|"
    r"longevity|proactive|healthspan|biological age|risk score|threshold|aging|ageing|epigenetic|glycan|"
    r"biomarker|hormone|estrogen|menopause|inflammation)\b", re.I)


def _prediagnosis(post: Post) -> bool:
    return bool(_PREDIAG_RE.search(post.content_snippet or ""))



def _hard_problems(text: str, avoid: list[str], allow_formula: bool) -> list[str]:
    """House-style/length/repetition violations worth a regenerate. Drops the 'before symptoms'
    formula flag when the post itself is about pre-diagnosis action (then it's on-topic).

    Stacked statements are left out on purpose. A whole regenerate told "fuse them into one
    sentence with a connector" is what produced the over-polished compound sentences; the caller
    sends a stacked comment to _fuse instead, which deletes a repeated sentence before it joins
    anything. Detection itself is unchanged (check_violations still reports it)."""
    probs = [p for p in _draft_problems(text, avoid, None) if not p.startswith("stacked statements")]
    if allow_formula:
        probs = [p for p in probs if "shows up" not in p]
    return probs


_FUSE_PROMPT = """This LinkedIn comment reads as separate statements placed side by side rather than one
person talking. Fix it with the smallest change that works.

Comment: "{text}"

In this order of preference:
1. If one sentence mostly repeats another, or turns it into a general principle, DELETE that
   sentence and return the rest word for word.
2. If two sentences are really one thought, say it as one sentence the way a person would out
   loud. There is no required joining word; connect it however that person would.
3. If it already reads like someone talking, return it completely unchanged.
Add nothing: no new idea, opinion, prediction, verdict or question. Keep every word you keep.

Examples:
  BEFORE: "Once a woman has a label, everyone stops looking. A diagnosis can end the investigation."
  AFTER:  "Once a woman has a label, everyone stops looking."
  BEFORE: "Time is the one luxury we cannot store. Investing in health is a sensible definition of longevity."
  AFTER:  "Investing in health is a sensible definition of longevity when time is the one luxury we cannot store."

Respond ONLY with JSON: {{"text": "..."}}"""


def _sentences(text: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if x.strip()]


def _norm_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _is_deletion(original: str, out: str) -> bool:
    """True when `out` is the original with whole sentences removed and nothing else changed."""
    orig = [_norm_words(x) for x in _sentences(original)]
    kept = [_norm_words(x) for x in _sentences(out)]
    if not kept or len(kept) >= len(orig):
        return False
    it = iter(orig)
    return all(any(k == o for o in it) for k in kept)  # kept is an in-order subsequence of orig


def _violation_kinds(text: str) -> set[str]:
    # "rambling (63 words) — ..." and "rambling (61 words) — ..." are the same violation.
    return {re.split(r" \(| —", v, maxsplit=1)[0] for v in check_violations(text)}


def _fuse(client: Client, text: str) -> str:
    """Repair a comment that still reads as stacked statements.

    Deletion first. The owner's diagnosis was that the first sentence is usually fine and the
    second re-says it, so the cheapest correct repair is usually to drop the second. This used to
    tell the model to keep every idea and join them with a connector, which produced the
    over-polished compound sentences reviewers then rejected.

    One small focused call succeeds far more often than asking the full drafter to start again.
    Returns the original on any failure, so this can only help."""
    if not text or not text.strip():
        return text
    try:
        out = str(extract_json(_call(
            settings.draft_model, _FUSE_PROMPT.format(text=text.strip()), 300, 25.0, effort="low",
        )).get("text", "")).strip()
    except Exception:
        return text
    if not out:
        return text
    # A pure deletion may be much shorter than the original, and that is the point of it. Anything
    # else is a rewrite and must not lose half the comment.
    if not _is_deletion(text, out) and len(out.split()) < 0.6 * len(text.split()):
        return text
    # Reject a repair that adds a violation the original did not have. Comparing kinds rather than
    # requiring a clean result: a comment with an unrelated tic would otherwise never be repaired.
    if _violation_kinds(out) - _violation_kinds(text):
        return text
    return out


def _reason_candidate(client: Client, post: Post, brief: str, plan: dict, avoid: list[str],
                      voice_ex_block: str, memory_block: str, shape: str) -> str:
    """Draft once; regenerate once ONLY if it trips a hard house-style/repetition rule.

    The previous approach-critique (_CRIT_PROMPT) + forced length-rewrite (_tighten) were tuned
    for the old model and flattened the current one into generic, process-y language, so they're
    dropped. Quality is carried by the anti-generic write rules + the humanizer (run inside
    generate), and every draft is still gated by check_violations downstream."""
    allow = _prediagnosis(post)
    text = _reason_generate_once(client, post, brief, plan, voice_ex_block, memory_block, shape)
    if not text:
        return ""
    probs = _hard_problems(text, avoid, allow)
    if probs:
        fix = "Also fix: " + "; ".join(probs) + f". Keep it specific and in {client.name}'s voice."
        retry = _reason_generate_once(client, post, brief, plan, voice_ex_block, memory_block,
                                      (shape + " " + fix).strip())
        # Only take the retry if it actually fixed something. This used to accept it blind, so a
        # regenerate that tripped the same rule replaced a draft that was no worse — one stacked
        # comment shipped that way in the benchmark. refine_draft already compared; this didn't.
        if retry and len(_hard_problems(retry, avoid, allow)) < len(probs):
            text = retry
    # The one repair for stacked statements (see _hard_problems). Cheap, and only fires on the
    # drafts that still read as statements placed side by side.
    if has_stacked_statements(text):
        text = _fuse(client, text)
    return text


_UNQUESTION_PROMPT = """This is a LinkedIn comment on SOMEONE ELSE'S post, written as {name}. It is
phrased as a question. Rewrite it as a statement.

Comment: "{text}"

The trap to avoid: do NOT convert the question into a claim that {name} did the thing being asked
about, and do NOT turn it into a clinical finding presented as their experience. The work belongs to
the person who wrote the post.
  WRONG: "How was the 70% heart-rate target individualized?"
      -> "My 70% heart-rate target is individualized."        (it is not theirs)
  WRONG: "Will you address how free estradiol affects glycan patterns?"
      -> "In my experience, free estradiol affects glycan patterns."   (invents a clinical claim)
  RIGHT: "How was the 70% heart-rate target individualized?"
      -> "Setting the target relative to each person's capacity is what makes this usable in a
          frail population."
  RIGHT: "Will you address how free estradiol affects glycan patterns?"
      -> "The hormone side of this is the part I will be listening for."

So: keep the same specific detail the question was about, and say why it matters, or what they will
be watching for. Assert no new fact, no study, no number and no clinical result. Do not claim the
post's work as their own. Do not add an opinion, a verdict or a prediction. Do not make it longer,
and do not end with a question mark.

Respond ONLY with JSON: {{"text": "..."}}"""


def _unquestion(client: Client, text: str) -> str:
    """Turn one question into a statement, keeping its point.

    Used only when EVERY option for a post came back as a question. The two candidates are
    generated in parallel and cannot see each other, so a post that invites a question gets two of
    them — measured at 3 of 9 posts for the client the reviewer flagged, which is exactly the
    "every second or third comment" she described. The draft-level question rate (9%) hides this
    completely, because the failures cluster onto the same posts.

    Returns the original on any failure, so the reviewer never ends up with less than she had."""
    if not text or not text.strip():
        return text
    try:
        out = str(extract_json(_call(
            settings.draft_model,
            _UNQUESTION_PROMPT.format(text=text.strip(), name=client.name or "them"),
            250, 25.0,
            effort="low",
        )).get("text", "")).strip()
    except Exception:
        return text
    if not out or _is_question(out) or check_violations(out):
        return text
    return out


def generate_drafts(client: Client, post: Post, count: int = 2, avoid_texts: list[str] | None = None,
                    voice_examples: list[str] | None = None, global_texts: list[str] | None = None,
                    sibling_texts: list[str] | None = None) -> list[str]:
    """Generate `count` candidates for a post. Each one reads the post, decides whether it is a
    human moment or not, and says what the client would naturally say, with the client's own view
    only where their material shows they hold it. Option 1 takes the post's main point, option 2 a
    different detail. The anti-repetition memory (`avoid_texts` + `global_texts`), the humanizer,
    the negation strip and the violation gate all run on each. `voice_examples` = comments a human
    edited and then approved (voice only). `sibling_texts` = comments OTHER profiles already made on
    THIS SAME post, so this client reacts to a different detail. Candidates run in parallel to stay
    well under the serverless time budget."""
    base_avoid = list(avoid_texts or [])
    brief = _expertise_brief(client)
    siblings_block = _siblings_block(sibling_texts, client.name)
    plan = _plan(client, post, brief, siblings_block)
    voice_ex_block = _voice_examples_block(voice_examples)
    profile = output_profile(base_avoid + list(global_texts or []))
    memory_block = "\n\n".join(b for b in (_self_awareness_block(profile), siblings_block, _avoid_block(base_avoid)) if b)
    # Reused-opener gate also considers other profiles' comments on this post, so a second profile
    # can't open the same way as the first.
    gate_avoid = base_avoid + [t.strip() for t in (sibling_texts or []) if t and t.strip()]
    # Option 1 answers the post's main point as plainly as you would in person; option 2 picks up a
    # different detail. They run in parallel and cannot see each other, so each is told its job
    # rather than "be different from the other one", which it could not check. A death or serious
    # illness overrides both: every option is a short condolence.
    n = max(1, count)
    _cond = " If the post is about a death or serious illness, ignore this and write a short condolence."
    shapes = ["This option replies to the post's main point, as plainly as you would say it in person." + _cond] + [
        "This option replies to one other specific detail in the post, a different one from its main "
        "point, with a different opening." + _cond] * (n - 1)

    # Resolve lazy relationships HERE, on the calling thread, before the pool starts. The workers
    # build _feedback_block(client), which reads client.feedback — a lazy relationship — and a
    # SQLAlchemy session is not thread-safe, so two workers could both trigger that load on the
    # same session at once. Done inside generate_drafts so every caller is covered, not just the
    # draft route (which only force-loads what its own safety pass reads).
    _ = list(getattr(client, "feedback", None) or [])

    def one(sh: str) -> str:
        return _reason_candidate(client, post, brief, plan, gate_avoid, voice_ex_block, memory_block, sh)

    try:
        with ThreadPoolExecutor(max_workers=min(n, 3)) as ex:
            results = list(ex.map(one, shapes))
    except Exception:
        results = [one(sh) for sh in shapes]
    out: list[str] = []
    for t in results:
        if t and t not in out:
            out.append(t)
    # Never hand the reviewer a post whose only options are both questions. The candidates run in
    # parallel and are blind to each other, so when a post invites a question they both ask one and
    # she is left with no alternative to pick. Convert the last one; if that fails it stays as it
    # was, so this can only add an option, never remove one.
    if len(out) > 1 and all(_is_question(t) for t in out):
        fixed = _unquestion(client, out[-1])
        if fixed and not _is_question(fixed) and fixed not in out[:-1]:
            out[-1] = fixed
    return out


_DECLAIM_PROMPT = """This LinkedIn comment, written as {name}, contains a claim that would need
fact-checking before it could be posted. No one on the team can verify claims, so the comment must be
rewritten until there is NOTHING left to check.

Comment: "{text}"

The unverifiable part(s): {flagged}

Rewrite it so it makes a plainer, safe observation instead — keep {name}'s voice and keep it about the
same post, but remove the claim entirely rather than softening it. Do not introduce any new fact,
number, study, mechanism, company, institution or person. Prefer a simple human reaction over anything
that asserts evidence. Keep it as short as the point needs.

The post being replied to:
\"\"\"{content}\"\"\"

Respond ONLY with JSON: {{"text": "..."}}"""


def strip_unverifiable(client: Client, post: Post, text: str, flagged: list[str]) -> str:
    """Rewrite a draft to remove claims the provenance pass flagged as `unverified`.

    Lara's standing rule is that a comment needing fact-checking is unusable — the team has no
    scientist to verify it. Provenance previously only LABELLED such claims, so they still reached
    her review queue; this makes the rule structural. Called by the draft route only when a flag
    actually fires, so it costs nothing on clean drafts. Returns the original on any failure."""
    if not text or not flagged:
        return text
    try:
        out = str(extract_json(_call(
            settings.draft_model,
            _DECLAIM_PROMPT.format(name=client.name, text=text,
                                   flagged="; ".join(f'"{f}"' for f in flagged[:3]),
                                   content=(post.content_snippet or "")[:1200]),
            400, 40.0, effort="low",
        )).get("text", "")).strip()
    except Exception:
        return text
    if not out:
        return text
    out = humanize_comments([out], _voice_block(client))[0]
    out = _strip_negation(out) or text
    # This rewrite runs after the drafter's own repair, so it needs the same one.
    return _fuse(client, out) if has_stacked_statements(out) else out


def _refine_once(client: Client, post: Post, current_text: str, instruction: str,
                 memory_block: str) -> str:
    rest = REFINE_PROMPT.format(
        name=client.name, voice=_voice_block(client), viewpoints=_viewpoints_block(client),
        benchmark=_benchmark_block(client), feedback=_feedback_block(client), memory=memory_block,
        content=post.content_snippet, current=current_text, instruction=instruction)
    content = _blocks((HOUSE_STYLE, True), (rest, False))  # cache HOUSE_STYLE across tweaks
    try:
        # effort="low": a tweak has to re-read the post and respect the hard rules, same as a
        # first draft — this path is where guardrails have historically been bypassed.
        data = extract_json(_call(settings.draft_model, content, 800, 50.0, effort="low"))
        revised = str(data["draft"])
    except (ValueError, KeyError):
        return ""
    out = humanize_comments([revised], _voice_block(client))
    out = _strip_negation(out[0] if out else revised)
    # _hard_problems no longer sends stacked statements to a regenerate, so a Tweak repairs them the
    # same way a first draft does. Without this the Tweak path would have no repair at all.
    return _fuse(client, out) if has_stacked_statements(out) else out


# Matches the "No question" chip's own wording AND the ways an operator phrases it free-hand.
# The first version of this missed the chip itself ("rewrite it as a PLAIN statement RATHER THAN a
# question"), which would have shipped the button with its enforcement dead — the regex is asserted
# against the exact chip text in the tests below for that reason.
_NO_QUESTION_RE = re.compile(
    r"(rather than a question|instead of a question|not a question|no question|without a question"
    r"|as an? (plain |simple )?statement|make it a statement|don'?t ask|do not ask|stop asking"
    r"|not end with a question mark|no question mark)", re.I)


def _wants_no_question(instruction: str) -> bool:
    """Did the operator ask for a statement rather than a question?

    Matches the 'No question' tweak chip and any free-text instruction that says the same thing.
    The refine prompt alone is not enough: the reviewer presses this button precisely because the
    model reached for a question, and asking it again in the same breath often returns another
    one — so refine_draft checks the result and retries."""
    return bool(_NO_QUESTION_RE.search(instruction or ""))


def refine_draft(client: Client, post: Post, current_text: str, instruction: str,
                 avoid_texts: list[str] | None = None, voice_examples: list[str] | None = None,
                 global_texts: list[str] | None = None, sibling_texts: list[str] | None = None) -> str:
    """Revise a single draft per an operator instruction — now through the SAME guardrails as
    generate_drafts (they were previously bypassed, which let the 'Curious'/praise-slop tics back in on
    every tweak). Builds the self-aware anti-repetition memory + sibling context, applies the operator
    instruction (its INTENT wins, but the house-style/length/no-curious rules OVERRIDE it), then runs the
    violation/length gate with one corrective regen and a hard tighten. A conflicting tweak prompt (e.g.
    'open with a strong reaction, 3 sentences') can no longer produce slop."""
    base_avoid = list(avoid_texts or [])
    profile = output_profile(base_avoid + list(global_texts or []))
    memory_block = "\n\n".join(
        b for b in (_self_awareness_block(profile), _siblings_block(sibling_texts, client.name), _avoid_block(base_avoid)) if b
    )
    gate_avoid = base_avoid + [t.strip() for t in (sibling_texts or []) if t and t.strip()]
    allow = _prediagnosis(post)

    text = _refine_once(client, post, current_text, instruction, memory_block)
    if not text:
        return current_text
    probs = _hard_problems(text, gate_avoid, allow)
    # A 'No question' tweak that comes back as another question has not done its job, so treat
    # that as a problem worth regenerating for — same as a house-style violation.
    unmet = _wants_no_question(instruction) and _is_question(text)
    # NO 26-word ceiling here. It existed only on this path, so pressing Tweak quietly cut a
    # comment that the drafter was free to write at any length, and it contradicted the house
    # style ("LENGTH: your judgement, taken from the post"). Genuine rambling is already a
    # violation inside _hard_problems at 60 words, which is where a length rule belongs.
    if probs or unmet:
        fix = ("Also strictly fix these: " + "; ".join(probs) + ". ") if probs else ""
        if unmet:
            fix += ("It must NOT be a question. Rewrite it as a plain statement that makes the same "
                    "point, and do not end with a question mark. ")
        retry = _refine_once(client, post, current_text, (instruction + " " + fix).strip(), memory_block)
        if retry and len(_hard_problems(retry, gate_avoid, allow)) <= len(probs):
            # Never accept a retry that still asks when the operator asked it not to.
            if not (_wants_no_question(instruction) and _is_question(retry)):
                text = retry
    # No _tighten pass here. That forced-shortening step gets only the bare sentence and
    # "make it shorter" — no house style, no voice samples, no viewpoints, no reasoning — so it
    # reliably flattened a comment's rhythm and voice. It was removed from the draft path for
    # that reason; leaving it on the tweak path meant the same comment was treated differently
    # depending on which button was pressed. Length is already enforced by the write rules in
    # the prompt and by the _hard_problems regenerate above, both of which keep full context.
    return text
