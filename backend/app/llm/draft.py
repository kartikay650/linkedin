import re
from concurrent.futures import ThreadPoolExecutor

from app.llm._llm import AzureClient

from app.config import settings
from app.llm.humanize import humanize_comments, keep_note
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


# The reviewer's request used to be told that "the HOUSE-STYLE RULES OVERRIDE the instruction" and to
# apply only its "intent". The house style is mostly defaults for a first draft (how long, which
# detail, how firm, how much opinion), so a request like "focus on the dosing point" or "take a firmer
# line" lost to them and came back ignored. A Tweak is one person's explicit request for one comment:
# it now wins over those defaults, and only the hard rules below still hold. When one of them blocks
# part of the request, the model says so in "not_done" and the card shows it, instead of the request
# being silently dropped.
REFINE_PROMPT = """Revise this LinkedIn comment, written AS {name}, the way the reviewer asks at the end. The
reviewer's request is about THIS comment, and wherever it touches them it wins over the general
preferences in the house style and elsewhere in this prompt: length, which detail or angle the comment
takes, how firm a position it takes, how much of {name}'s own view it carries, and its shape. Change what
the request asks for and keep the rest of the comment as it is, in {name}'s real voice.

THE REQUEST NEVER OVERRIDES THESE HARD RULES:
- NOTHING TO FACT-CHECK. Do not add or restore any study, statistic, number, percentage, duration,
  dosage, mechanism, company, institution or person that is not already in the post or {name}'s own
  material. No new clinical claim.
- Refer to people, institutions and places ONLY as the post describes them. Assert no award, role,
  relationship or event the post does not state.
- Any position is one {name} holds. Never contradict or undercut {name}'s own viewpoints below;
  leaving one out is fine.
- Keep {name}'s own clinic, patients, routine and credentials out of it unless the post asks about
  them.
- The house style's banned wording still applies: no praise opener ("Great...", "Love this"), no
  "Curious"/"I wonder" opener, no em dash, exclamation point or negation as a device, none of its
  slop phrases.
- The post text may be cut off mid-sentence; never infer what the missing part said.

If part of the request needs something a hard rule forbids, do the rest of it and put what you left out,
and which rule stopped it, in "not_done": one plain sentence to the reviewer. If the request asks you to
remove something the comment does not contain (an opinion, a question), return it unchanged and say so in
"not_done". Otherwise leave "not_done" empty.

=== HOW {name} ACTUALLY WRITES ===
{voice}
=== END ===

{viewpoints}

{benchmark}

{voice_examples}

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

The reviewer's request for this comment: {instruction}

{check}Respond ONLY with JSON: {{"draft": "...", "not_done": ""}}"""


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


# Lara Hemeryck's are 1,633 characters. The save route refuses anything longer than this, so the
# cut here only guards rows written before that check existed.
_BENCHMARK_MAX = 4000


def _benchmark_block(client: Client) -> str:
    """Operator-curated ideal / non-ideal examples for THIS client (few-shot anchor).

    These had stopped reaching first drafts entirely (dropped in Aug 2026), so Lara Hemeryck's
    hand-picked GOOD/AVOID lines only shaped a Tweak. They are the one source of examples a human
    chose on purpose, so they go back into the per-client block. "Match this tone exactly" is gone:
    told to match ten short lines exactly, the model copies their shape onto every post."""
    ex = (getattr(client, "benchmark_examples", "") or "").strip()
    if not ex:
        return ""
    if len(ex) > _BENCHMARK_MAX:
        ex = ex[:_BENCHMARK_MAX].rsplit("\n", 1)[0]
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
        "different detail of the post, in different words. Do not reword these or make their point. "
        "On a personal moment or a milestone, the same warm reaction in your own words is fine:\n"
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
        return _call(settings.relevance_model, _BRIEF_PROMPT.format(name=client.name, material="\n".join(mats)), 700, 30.0,
                     effort="low").content[0].text.strip()
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
1. SAID TWICE? If one sentence repeats another in other words, hands the post's own point back, or
   turns the other into a general principle, delete it, whichever one it is. If the two are really
   one thought, say it as one sentence the way you would out loud. Two sentences are fine when
   each says something of its own.
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

Decide which of these it is:
- One sentence mostly repeats another, hands the post's own point back, or turns the other into a
  general principle: DELETE that sentence, whichever one it is, and return the rest word for word.
- Two sentences are really one thought: say it as one sentence the way a person would out loud.
  There is no required joining word; connect it however that person would.
- It already reads like someone talking, with each sentence doing its own work: return it
  completely unchanged. Plenty of good two-sentence comments look like this.
Add nothing: no new idea, opinion, prediction, verdict or question. Keep every word you keep.

Examples:
  BEFORE: "Once a woman has a label, everyone stops looking. A diagnosis can end the investigation."
  AFTER:  "Once a woman has a label, everyone stops looking."
  BEFORE: "Quite a pairing for 2027. The New York programme should be worth the trip."
  AFTER:  unchanged — each sentence does its own work and both read as speech.

{keep}Respond ONLY with JSON: {{"text": "..."}}"""


# Titles and Latin abbreviations, plus runs of initials like "U.S.". A single capital is NOT an
# abbreviation here: "vitamin D." and "hepatitis B." end sentences in this client base.
_ABBREV_RE = re.compile(r"(?:\b(?:Dr|Mr|Mrs|Ms|Prof|St|vs|etc|approx|e\.g|i\.e)\.|(?:\b[A-Z]\.){2,})$")


def _sentences(text: str) -> list[str]:
    """Split a comment into sentences without breaking "Dr. Smith", "e.g. this" or "U.S. data"."""
    parts = [x.strip() for x in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if x.strip()]
    out: list[str] = []
    for x in parts:
        # A fragment that starts lower-case continues the previous one ("U.S. data", "e.g. walking").
        if out and (_ABBREV_RE.search(out[-1]) or x[:1].islower()):
            out[-1] = out[-1] + " " + x
        else:
            out.append(x)
    return out


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


def _fuse(client: Client, text: str, keep: str = "") -> str:
    """Repair a comment that still reads as stacked statements.

    Deletion first. The owner's diagnosis was that the first sentence is usually fine and the
    second re-says it, so the cheapest correct repair is usually to drop the second. This used to
    tell the model to keep every idea and join them with a connector, which produced the
    over-polished compound sentences reviewers then rejected.

    One small focused call succeeds far more often than asking the full drafter to start again.
    Returns the original on any failure, so this can only help. `keep` is the reviewer's Tweak
    request, on the Tweak path only."""
    if not text or not text.strip():
        return text
    try:
        out = str(extract_json(_call(
            settings.draft_model,
            _FUSE_PROMPT.format(text=text.strip(), keep=keep_note(keep, "the comment")),
            300, 25.0, effort="low",
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


# The same person-scoped trigger as HOUSE_STYLE. "A post about serious illness" would match half
# of a health feed; "someone has died or is seriously ill" is the case that needs a condolence.
_CONDOLENCE = " If someone has died or is seriously ill, ignore this and write a short condolence."


def _draft_setup(client: Client, post: Post, avoid_texts, voice_examples, global_texts, sibling_texts):
    """Everything a first draft is built from, shared by generate_drafts and angle_draft so the two
    can never drift apart."""
    # Resolve lazy relationships HERE, on the calling thread, before any pool starts. The workers
    # build _feedback_block(client), which reads client.feedback — a lazy relationship — and a
    # SQLAlchemy session is not thread-safe, so two workers could both trigger that load on the
    # same session at once.
    _ = list(getattr(client, "feedback", None) or [])
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
    return brief, plan, voice_ex_block, memory_block, gate_avoid


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
    brief, plan, voice_ex_block, memory_block, gate_avoid = _draft_setup(
        client, post, avoid_texts, voice_examples, global_texts, sibling_texts)
    # Option 1 answers the post's main point as plainly as you would in person; option 2 picks up a
    # different detail. They run in parallel and cannot see each other, so each is told its job
    # rather than "be different from the other one", which it could not check. A death or serious
    # illness overrides both: every option is a short condolence.
    n = max(1, count)
    shapes = ["This option replies to the post's main point, as plainly as you would say it in person." + _CONDOLENCE] + [
        "This option replies to one other specific detail in the post, a different one from its main "
        "point, with a different opening. If the post has only one point, or it is a personal moment "
        "or a milestone, give the same kind of reply in different words instead." + _CONDOLENCE] * (n - 1)

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


_STOPWORDS = frozenset("""
this that these those with from have has had what when where which while your yours their them they
about been being were will would could should into over under also just more most much very really
such than then there here some something only even still because make makes made like well good
great every each other another same both many much does doing done dont isnt thats youre its
""".split())


def _content_words(text: str, exclude: set[str] | frozenset = frozenset()) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", (text or "").lower().replace("\u2019", "'"))
            if len(w) > 3 and w not in _STOPWORDS and w not in exclude}


def _overlap(a: str, b: str, exclude: set[str] | frozenset = frozenset()) -> float:
    """Share of the shorter comment's own words that also appear in the other one. Stopwords and
    the post's own words are left out: every comment on a post shares its topic nouns, so counting
    them made two genuinely different comments look like the same one."""
    wa, wb = _content_words(a, exclude), _content_words(b, exclude)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


# A new angle that shares more than half its content words with something the reviewer already
# passed on is the same comment reworded, which is what "Regenerate" kept producing.
_ANGLE_MAX_OVERLAP = 0.5
_CONDOLENCE_RE = re.compile(r"\b(sorry for|sorry to hear|so sorry|condolence|rest in peace|thinking of you|"
                            r"your loss|passed away|my sympathies|deepest sympathy)\b", re.I)


def angle_draft(client: Client, post: Post, taken: list[str], avoid_texts: list[str] | None = None,
                voice_examples: list[str] | None = None, global_texts: list[str] | None = None,
                sibling_texts: list[str] | None = None) -> str:
    """One new comment on a different angle from everything the reviewer has already seen.

    "Regenerate" replaces both options with two fresh ones that cannot see what they replace, so
    it often came back with the same point in new words. This goes through the full first-draft
    path (same prompt, same gates) with one extra instruction: the comments already on the table,
    and a request to react to something else in the post. At most one retry, which covers both a
    house-style failure and a reworded repeat, so it never costs more than a first draft."""
    taken = [t.strip() for t in taken if t and t.strip()]
    brief, plan, voice_ex_block, memory_block, gate_avoid = _draft_setup(
        client, post, avoid_texts, voice_examples, global_texts, sibling_texts)
    listed = "\n".join(f"- {t}" for t in taken[:6])
    shape = ("The reviewer has already seen these comments for this post and wants a different one:\n"
             + listed + "\nReact to a different detail or a different part of the post from all of "
             "them, in different words, with a different opening. If the post has only one point, or "
             "it is a personal moment, say it differently instead." + _CONDOLENCE)
    allow = _prediagnosis(post)
    gate = gate_avoid + taken
    post_words = _content_words(post.content_snippet or "")
    # Two condolences are meant to say the same thing; never push one toward "a different point".
    condolence = any(_CONDOLENCE_RE.search(t) for t in taken)

    def is_repeat(t: str) -> bool:
        return not condolence and any(_overlap(t, x, post_words) > _ANGLE_MAX_OVERLAP for x in taken)

    def score(t: str) -> int:
        return len(_hard_problems(t, gate, allow)) + (1 if is_repeat(t) else 0)

    text = _reason_generate_once(client, post, brief, plan, voice_ex_block, memory_block, shape)
    if not text:
        return ""
    if score(text):
        probs = _hard_problems(text, gate, allow)
        if is_repeat(text):
            probs.append("it makes the same point as one of the comments above")
        fix = "Also fix: " + "; ".join(probs) + f". Keep it specific and in {client.name}'s voice."
        retry = _reason_generate_once(client, post, brief, plan, voice_ex_block, memory_block,
                                      shape + " " + fix)
        if retry and score(retry) < score(text):
            text = retry
    if has_stacked_statements(text):
        text = _fuse(client, text)
    return text


_DECLAIM_PROMPT = """This LinkedIn comment, written as {name}, contains a claim that would need
fact-checking before it could be posted. No one on the team can verify claims, so the comment must be
rewritten until there is NOTHING left to check.

Comment: "{text}"

The unverifiable part(s): {flagged}

Rewrite it so it makes a plainer, safe observation instead — keep {name}'s voice and keep it about the
same post, but remove the claim entirely rather than softening it. Do not introduce any new fact,
number, study, mechanism, company, institution or person. Prefer a simple human reaction over anything
that asserts evidence. Keep it as short as the point needs.

{keep}The post being replied to:
\"\"\"{content}\"\"\"

Respond ONLY with JSON: {{"text": "..."}}"""


def strip_unverifiable(client: Client, post: Post, text: str, flagged: list[str], keep: str = "") -> str:
    """Rewrite a draft to remove claims the provenance pass flagged as `unverified`.

    Lara's standing rule is that a comment needing fact-checking is unusable — the team has no
    scientist to verify it. Provenance previously only LABELLED such claims, so they still reached
    her review queue; this makes the rule structural. Called by the draft route only when a flag
    actually fires, so it costs nothing on clean drafts. Returns the original on any failure.

    `keep` is the reviewer's Tweak request (Tweak path only). The claim still goes, since that is a
    hard rule and the route tells her what was taken out, but the rest of what she asked for stays."""
    if not text or not flagged:
        return text
    try:
        out = str(extract_json(_call(
            settings.draft_model,
            _DECLAIM_PROMPT.format(name=client.name, text=text,
                                   flagged="; ".join(f'"{f}"' for f in flagged[:3]),
                                   content=(post.content_snippet or "")[:1200],
                                   keep=keep_note(keep, "the comment, apart from the claim to remove,")),
            400, 40.0, effort="low",
        )).get("text", "")).strip()
    except Exception:
        return text
    if not out:
        return text
    out = humanize_comments([out], _voice_block(client), keep=keep)[0]
    out = _strip_negation(out) or text
    # This rewrite runs after the drafter's own repair, so it needs the same one.
    return _fuse(client, out, keep) if has_stacked_statements(out) else out


def _refine_once(client: Client, post: Post, current_text: str, instruction: str,
                 memory_block: str, voice_ex_block: str = "", check: str = "") -> tuple[str, str]:
    """One Tweak call. Returns (text, not_done): not_done is the model's own sentence to the
    reviewer about any part of the request a hard rule stopped, or that was already done.

    `check` is the gate's findings on a first attempt, retry only. It goes on its own labelled
    line rather than onto her request: appended to the request, the model read the gate's "fix
    the length" as something she had asked for, and the humanizer was told to protect it."""
    rest = REFINE_PROMPT.format(
        name=client.name, voice=_voice_block(client), viewpoints=_viewpoints_block(client),
        benchmark=_benchmark_block(client), voice_examples=voice_ex_block,
        feedback=_feedback_block(client), memory=memory_block,
        content=post.content_snippet, current=current_text, instruction=instruction,
        check=(f"An automatic check of your first attempt found these. They are not part of the "
               f"reviewer's request; fix them while still doing what the reviewer asked: {check}\n\n"
               if check else ""))
    content = _blocks((HOUSE_STYLE, True), (rest, False))  # cache HOUSE_STYLE across tweaks
    try:
        # effort="low": a tweak has to re-read the post and respect the hard rules, same as a
        # first draft — this path is where guardrails have historically been bypassed.
        data = extract_json(_call(settings.draft_model, content, 800, 50.0, effort="low"))
        # Valid JSON that is not an object (a list, a string) raises TypeError on the lookup; a
        # null draft would otherwise be saved as the word "None". Both are a failed call (502).
        revised = str(data["draft"] or "").strip()
        not_done = " ".join(str(data.get("not_done") or "").split())[:300]
    except (ValueError, KeyError, AttributeError, TypeError):
        return "", ""
    if not revised:
        return "", ""
    out = humanize_comments([revised], _voice_block(client), keep=instruction)
    return _strip_negation(out[0] if out else revised), not_done


# Matches the "No question" chip's own wording AND the ways an operator phrases it free-hand.
# The first version of this missed the chip itself ("rewrite it as a PLAIN statement RATHER THAN a
# question"), which would have shipped the button with its enforcement dead — the regex is asserted
# against the exact chip text in the tests below for that reason.
_NO_QUESTION_RE = re.compile(
    r"(rather than a question|instead of a question|not a question|no question|without a question"
    r"|as an? (plain |simple )?statement|make it a statement|don'?t ask|do not ask|stop asking"
    r"|not end with a question mark|no question mark)", re.I)


# Tweak chips. The wording lives on the server, keyed by an id the dashboard sends, so a chip can
# never drift from the checks below that enforce it, and so chip use can be logged by id. No chip
# asks for a claim, a credential or a story about the client's own work, and REFINE_PROMPT's hard
# rules forbid all three on every Tweak. ("No question" used to say "say it as an observation from
# her own experience or practice", which turned every press into the self-insertion reviewers
# delete.) "shorter" is handled by shorten_draft and "angle" by angle_draft; they are
# listed so the route can validate an id in one place.
TWEAK_CHIPS = {
    "angle": "",
    "shorter": "make it shorter: cut whatever is not doing work and keep its point",
    "conversational": "make it sound more like something said out loud to the author: plainer "
                      "words and a looser rhythm, the same point, and no longer than it is now",
    "personality": "let more of this person's own personality come through, taken from how they "
                   "write and the examples above: their word choice, their bluntness or humour. "
                   "Do not add a claim, a credential, or anything about their own work",
    "warmer": "make it warmer and more human, without any praise opener or clinical jargon",
    "no_question": "rewrite it as a plain statement rather than a question: keep the same point and "
                   "the same specific detail, and do not end with a question mark",
    # Spelled out because "personal opinion" alone let the model decide a judgement such as "this is
    # the part that matters" was a reaction, return the comment unchanged, and do so on every press.
    "remove_opinion": "remove every view of this person's own (a judgement, a stance, a prediction, "
                      "what matters most or what someone should do) and any unverified claim; keep "
                      "only a plain reaction to what the post itself says",
}


# What the card says when a Tweak changed nothing, instead of showing the same comment as if it had
# worked (Umar pressed "Remove opinion" three times and got the same comment each time).
TWEAK_NOOP = {
    "shorter": "Couldn't make it shorter without losing its point. Tell it what to cut, or edit it directly.",
    "conversational": "It already reads as spoken, so nothing changed. Tell it which words feel written, or try Different angle.",
    "personality": "Nothing changed. Tell it what to bring out, or try Different angle.",
    "warmer": "Nothing changed. Tell it what feels cold, or try Different angle.",
    "no_question": "There's no question in it to remove, so nothing changed.",
    "remove_opinion": "No opinion found to remove. Try Different angle, or tell it what to drop.",
    "": "It came back unchanged. Try saying exactly what to add, drop or change.",
}
_NO_QUESTION_FAILED = ("Couldn't turn this into a statement without losing its point. Edit it directly, "
                       "or try Different angle.")


def tweak_noop_note(chip: str | None, instruction: str, current: str, not_done: str) -> str:
    """The plain sentence for a Tweak that changed nothing. A chip gets its fixed wording; free text
    gets the model's own reason when it gave one."""
    if _wants_no_question(instruction) and _is_question(current):
        return _NO_QUESTION_FAILED
    if chip:
        return TWEAK_NOOP.get(chip) or TWEAK_NOOP[""]
    return not_done or TWEAK_NOOP[""]


def same_words(a: str, b: str) -> bool:
    """Same words in the same order, ignoring case and punctuation."""
    return _norm_words(a) == _norm_words(b)


def tweak_unchanged(revised: str, current: str) -> bool:
    """Did a Tweak change nothing the reviewer would count as a change?

    Same words is not enough on its own. A "No question" that turns "?" into "." has done exactly
    what was asked, and so has a rewrite whose only change is taking out a banned em dash,
    exclamation point or emoji; throwing those away kept the question or the banned mark on the
    card and told her nothing changed. Any other punctuation or case change (a comma moved, a
    capital) is still the same comment to her."""
    return (same_words(revised, current)
            and _is_question(revised) == _is_question(current)
            and not (_violation_kinds(current) - _violation_kinds(revised)))


_PICK_PROMPT = """A reviewer wants this LinkedIn comment, written as {name}, made shorter. Here it is, one
numbered sentence per line:
{numbered}

Pick the ONE sentence that works best as the whole comment on its own: it makes sense without the
others, it responds to the post, and it is the one {name} would most naturally say. If none of
them makes sense on its own, answer 0.

The post:
\"\"\"{content}\"\"\"

Respond ONLY with JSON: {{"pick": <number>}}"""


def shorten_draft(client: Client, post: Post, current_text: str, **context) -> tuple[str, str]:
    """The "Shorter" chip.

    With two or more sentences, keep one of them word for word. The reviewer's complaint is almost
    always that the comment says one thing and then says it again, so the shorter comment is
    usually already sitting inside the long one; rewriting it from scratch lost the wording she
    was happy with and often came back about as long. One small call picks the sentence, and it is
    returned verbatim: no humanizer, no negation strip, nothing to re-introduce a tic. A comment
    that is already one sentence, or whose sentences do not stand alone, gets a tight rewrite
    through the normal Tweak path instead."""
    sents = _sentences(current_text)
    if len(sents) >= 2:
        numbered = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(sents))
        try:
            pick = int(extract_json(_call(
                settings.relevance_model,
                _PICK_PROMPT.format(name=client.name, numbered=numbered,
                                    content=(post.content_snippet or "")[:1500]),
                100, 20.0, effort="low",
            )).get("pick", 0))
        except Exception:
            pick = 0
        if 1 <= pick <= len(sents):
            return sents[pick - 1], ""
    return refine_draft(client, post, current_text, TWEAK_CHIPS["shorter"], **context)


# Gate checks that can contradict an explicit Tweak request, and what the card says when the retry
# enforced one. The others (banned wording, a repeated opening) are either hard rules the model
# reports itself in not_done or nothing a reviewer would ask for, so they get no note.
_GATE_NOTES = {
    "rambling": "Kept it under 60 words, the house limit for a comment.",
    "over-certainty": 'Softened the certainty (words like "definitely" or "proves"): the house style '
                      "keeps science claims nuanced.",
    "conditional advice": 'Left out "I would..." advice to the author: the house style doesn\'t allow it.',
    "hedge tic": 'Reworded "tends to" / "seems to": the house style treats it as a verbal tic.',
}


def _gate_note(first_probs: list[str], final: str, gate_avoid: list[str], allow: bool) -> str:
    """Plain sentences for the gate checks the first attempt failed and the accepted retry fixed."""
    def kinds(probs: list[str]) -> set[str]:
        return {re.split(r" \(| —", p, maxsplit=1)[0] for p in probs}
    fixed = kinds(first_probs) - kinds(_hard_problems(final, gate_avoid, allow))
    return " ".join(note for kind, note in _GATE_NOTES.items() if kind in fixed)


def _wants_no_question(instruction: str) -> bool:
    """Did the operator ask for a statement rather than a question?

    Matches the 'No question' tweak chip and any free-text instruction that says the same thing.
    The refine prompt alone is not enough: the reviewer presses this button precisely because the
    model reached for a question, and asking it again in the same breath often returns another
    one — so refine_draft checks the result and retries."""
    return bool(_NO_QUESTION_RE.search(instruction or ""))


def refine_draft(client: Client, post: Post, current_text: str, instruction: str,
                 avoid_texts: list[str] | None = None, voice_examples: list[str] | None = None,
                 global_texts: list[str] | None = None,
                 sibling_texts: list[str] | None = None) -> tuple[str, str]:
    """Revise a single draft per a reviewer's request — through the SAME guardrails as
    generate_drafts (they were previously bypassed, which let the 'Curious'/praise-slop tics back in on
    every tweak). Builds the self-aware anti-repetition memory + sibling context, applies the request
    (it wins over the house style's defaults; the hard rules and banned wording still hold), then runs
    the violation gate with one corrective regen. A conflicting tweak prompt (e.g. 'open with a strong
    reaction') still can't produce slop: the gate catches it.

    Returns (text, not_done). Empty text means the call failed. Text equal to `current_text` means
    nothing changed, and the route tells the reviewer so. Every pass after the model (humanizer,
    repair, fact-check rewrite) is handed the request so it does not undo it. Two things can still
    overrule it, and both are reported in not_done rather than dropped silently: a hard rule (the
    model's own sentence, or the route's fact-check note) and the gate's retry (_gate_note)."""
    base_avoid = list(avoid_texts or [])
    profile = output_profile(base_avoid + list(global_texts or []))
    memory_block = "\n\n".join(
        b for b in (_self_awareness_block(profile), _siblings_block(sibling_texts, client.name), _avoid_block(base_avoid)) if b
    )
    gate_avoid = base_avoid + [t.strip() for t in (sibling_texts or []) if t and t.strip()]
    allow = _prediagnosis(post)
    # The edited examples reach a Tweak too. "More personality" has nothing to draw on without
    # them, and every other chip is better anchored with them.
    _ = list(getattr(client, "feedback", None) or [])
    voice_ex_block = _voice_examples_block(voice_examples)

    text, not_done = _refine_once(client, post, current_text, instruction, memory_block, voice_ex_block)
    if not text:
        # Empty means the call failed. Returning current_text here made the route treat her own
        # words as the tool's rewrite; the route reports the failure instead.
        return "", ""
    # _hard_problems no longer sends stacked statements to a regenerate, so a Tweak repairs them
    # the way a first draft does. Done BEFORE the gate: deleting a repeated sentence can also
    # remove a trailing question or the extra words, which saves the whole retry.
    if has_stacked_statements(text):
        text = _fuse(client, text, instruction)
    probs = _hard_problems(text, gate_avoid, allow)
    # A 'No question' tweak that comes back as another question has not done its job, so treat
    # that as a problem worth regenerating for — same as a house-style violation.
    unmet = _wants_no_question(instruction) and _is_question(text)
    # NO 26-word ceiling here. It existed only on this path, so pressing Tweak quietly cut a
    # comment that the drafter was free to write at any length, and it contradicted the house
    # style ("LENGTH: your judgement, taken from the post"). Genuine rambling is already a
    # violation inside _hard_problems at 60 words, which is where a length rule belongs.
    if probs or unmet:
        fix = ("; ".join(probs) + ". ") if probs else ""
        if unmet:
            fix += ("It must NOT be a question. Rewrite it as a plain statement that makes the same "
                    "point, and do not end with a question mark. ")
        retry, retry_not_done = _refine_once(client, post, current_text, instruction,
                                             memory_block, voice_ex_block, check=fix.strip())
        if retry and len(_hard_problems(retry, gate_avoid, allow)) <= len(probs):
            # Never accept a retry that still asks when the operator asked it not to.
            if not (_wants_no_question(instruction) and _is_question(retry)):
                text = _fuse(client, retry, instruction) if has_stacked_statements(retry) else retry
                # The gate can overrule her ("expand on this" vs the 60-word limit, "firmer" vs
                # the over-certainty check). Say what it enforced instead of dropping it silently.
                not_done = " ".join(x for x in (retry_not_done, _gate_note(probs, text, gate_avoid, allow)) if x)
    if _wants_no_question(instruction) and _is_question(text):
        # Both attempts still asked. This used to return the question anyway, so "No question"
        # visibly did nothing. The dedicated converter is the one first drafts use when every
        # option came back as a question; if it fails too, hand back her text unchanged and the
        # route says it couldn't be done, rather than showing a question as the result.
        fixed = _unquestion(client, text)
        if _is_question(fixed):
            return current_text, ""
        text = fixed
    # No _tighten pass here. That forced-shortening step gets only the bare sentence and
    # "make it shorter" — no house style, no voice samples, no viewpoints, no reasoning — so it
    # reliably flattened a comment's rhythm and voice. It was removed from the draft path for
    # that reason; leaving it on the tweak path meant the same comment was treated differently
    # depending on which button was pressed. Length is already enforced by the write rules in
    # the prompt and by the _hard_problems regenerate above, both of which keep full context.
    return text, not_done
