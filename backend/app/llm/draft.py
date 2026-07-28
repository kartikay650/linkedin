import re

import anthropic

from app.config import settings
from app.llm.humanize import humanize_comments
from app.llm.style import HOUSE_STYLE, STRONG_EXAMPLES, check_violations, has_formula, has_negation_device
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

PROMPT = """You are writing ONE LinkedIn comment reply AS {name}. The single most important thing: the reply must be \
indistinguishable from something she typed herself. Not "in her style" — actually hers.

=== HOW SHE ACTUALLY WRITES (study this hard, match it exactly) ===
{voice}
=== END ===

{voice_examples}

{brand}

{house_style}

{examples}

{benchmark}

{feedback}

{avoid}

The post she is replying to:
Author: {author}
\"\"\"
{content}
\"\"\"

Write ONE reply that:
- sounds exactly like her voice samples above — same sentence length, rhythm, vocabulary level, and bluntness,
- reacts to one specific thing in THIS post, never a generic reaction that could sit under any post,
- MATCHES THE POST'S REGISTER: if this is a personal story, reflection, or something vulnerable, be warm and human and skip the science, data, and opinions; if it's light or casual, keep it light; bring the expert/scientific voice ONLY when the post is genuinely technical or scientific,
- does NOT force an opinion where none is needed: default to a specific observation or a genuine question, and take a firm stance ONLY when the post is squarely about her expertise and clearly invites one,
- is SHORT (one or two sentences, ~15-25 words) with at most one claim,
- is structurally different from her recent comments shown above, and NEVER uses the "shows up before symptoms/diagnosis/a scan" construction or the words "tends to" / "seems to",
- obeys every house-style and content-safety rule above, and obeys her CTA rules and guardrails.
{nudge}
Respond ONLY with JSON: {{"drafts": ["your one reply"]}}"""

REFINE_PROMPT = """Revise this LinkedIn comment, written AS {name}, following the operator's instruction. \
Keep it unmistakably in her voice and obey every house-style rule.

=== HOW SHE ACTUALLY WRITES ===
{voice}
=== END ===

{house_style}

{benchmark}

{feedback}

The post being replied to:
\"\"\"
{content}
\"\"\"

Current reply:
\"\"\"
{current}
\"\"\"

Operator's instruction: {instruction}

Rewrite the reply to follow that instruction while staying in her exact voice and inside every house-style and \
content-safety rule above. Respond ONLY with JSON: {{"draft": "..."}}"""


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
            message = _client.with_options(max_retries=1, timeout=30.0).messages.create(
                model=settings.draft_model,
                max_tokens=400,
                extra_body={"thinking": {"type": "disabled"}},
                messages=[{"role": "user", "content": STRIP_NEGATION_PROMPT.format(text=out)}],
            )
            cand = str(extract_json(message).get("text", "")).strip()
            if cand:
                out = cand
        except Exception:
            break
    return out


def _voice_block(client: Client) -> str:
    """The person's real voice: verbatim samples first (strongest signal), then the
    written description. Falls back to the legacy tone_profile."""
    parts = []
    if (client.voice_samples or "").strip():
        parts.append("Verbatim examples of their own words:\n" + client.voice_samples.strip())
    guide = (client.voice_guide or client.tone_profile or "").strip()
    if guide:
        parts.append("How they write:\n" + guide)
    return "\n\n".join(parts) if parts else "Direct, plain, specific. No fluff."


def _brand_block(client: Client) -> str:
    sections = [
        ("Their viewpoints / stances", client.viewpoints),
        ("Audience they're speaking to", client.audience),
        ("Key messages / proof points", client.key_messages),
        ("Their personal why / stories (use for genuine human touch, never fabricate)", client.personal_story),
        ("CTA rules", client.cta_rules),
        ("Guardrails (hard rules)", client.guardrails),
    ]
    parts = [f"{label}:\n{value.strip()}" for label, value in sections if value and value.strip()]
    return ("=== BRAND CONTEXT ===\n" + "\n\n".join(parts) + "\n=== END ===") if parts else ""


def _benchmark_block(client: Client) -> str:
    """Operator-curated ideal / non-ideal examples for THIS client (few-shot anchor)."""
    ex = (getattr(client, "benchmark_examples", "") or "").strip()
    if not ex:
        return ""
    return (
        "=== APPROVED EXAMPLES FOR THIS CLIENT (match this tone exactly — hand-picked as ideal/non-ideal) ===\n"
        + ex
        + "\n=== END ==="
    )


def _feedback_block(client: Client) -> str:
    """Most recent operator corrections, auto-applied to every new draft."""
    notes = getattr(client, "feedback", None) or []
    recent = sorted(notes, key=lambda f: f.id, reverse=True)[:5]
    lines = "\n".join(f"- {n.note.strip()}" for n in recent if (n.note or "").strip())
    if not lines:
        return ""
    return (
        "=== OPERATOR GUIDANCE (recent corrections — apply every one) ===\n"
        + lines
        + "\n=== END ==="
    )


def _voice_examples_block(texts: list[str] | None) -> str:
    """Comments the team actually approved/posted for THIS client — the learning loop's
    gold standard. Grows as the team works, so voice fidelity improves over time without
    manual seeding. Match their voice; don't copy their structure (stay varied)."""
    ex = [t.strip() for t in (texts or []) if t and t.strip()][:8]
    if not ex:
        return ""
    lines = "\n".join(f"- {t}" for t in ex)
    return (
        "=== COMMENTS THE TEAM APPROVED FOR THIS CLIENT — the gold standard for how she really sounds ===\n"
        "Learn the voice from these: their tone, rhythm, sentence length, vocabulary, and bluntness. "
        "Match that. But do NOT copy their structure or phrasings — stay varied.\n" + lines + "\n=== END ==="
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
        "different sentence shape, a different angle. Do not reuse their phrasings, and never repeat "
        "the 'shows up before symptoms/diagnosis/a scan' construction.\n" + lines + "\n=== END ==="
    )


def _opener(text: str) -> str:
    return " ".join(re.findall(r"[a-z']+", (text or "").lower())[:3])


def _draft_problems(text: str, avoid_texts: list[str] | None) -> list[str]:
    """Deterministic quality gate: house-style violations (incl. the over-used template,
    length, negation, slop) plus reusing a recent comment's opening."""
    problems = list(check_violations(text))
    op = _opener(text)
    if op and any(op == _opener(t) for t in (avoid_texts or [])):
        problems.append("same opening as a recent comment")
    return problems


def _generate_once(client: Client, post: Post, avoid_block: str, nudge: str, voice_ex_block: str = "") -> str:
    message = _client.with_options(max_retries=1, timeout=45.0).messages.create(
        model=settings.draft_model,
        max_tokens=800,
        # Thinking off (pinned SDK); the house style + humanizer carry the quality rules.
        extra_body={"thinking": {"type": "disabled"}},
        messages=[{
            "role": "user",
            "content": PROMPT.format(
                name=client.name,
                voice=_voice_block(client),
                voice_examples=voice_ex_block,
                brand=_brand_block(client),
                house_style=HOUSE_STYLE,
                examples=STRONG_EXAMPLES,
                benchmark=_benchmark_block(client),
                feedback=_feedback_block(client),
                avoid=avoid_block,
                nudge=("\n" + nudge if nudge else ""),
                author=post.author_name,
                content=post.content_snippet,
            ),
        }],
    )
    try:
        data = extract_json(message)
        drafts = [str(d) for d in data["drafts"] if str(d).strip()]
    except (ValueError, KeyError):
        return ""
    drafts = humanize_comments(drafts, _voice_block(client))
    drafts = [_strip_negation(d) for d in drafts]  # hard-enforce: no negation-as-a-device
    return drafts[0] if drafts else ""


def _one_candidate(client: Client, post: Post, avoid: list[str], shape_nudge: str, voice_ex_block: str) -> str:
    """One reply + a single self-correction pass if it trips the quality gate."""
    block = _avoid_block(avoid)
    text = _generate_once(client, post, block, nudge=shape_nudge, voice_ex_block=voice_ex_block)
    if not text:
        return ""
    problems = _draft_problems(text, avoid)
    if problems:
        nudge = (
            (shape_nudge + " ") if shape_nudge else ""
        ) + (
            "Your previous attempt failed for these reasons: " + "; ".join(problems) + ". "
            "Write a COMPLETELY different comment that fixes them — different opening word, different "
            "structure, at most one claim, one or two short sentences, never the "
            "'shows up before symptoms/diagnosis/a scan' construction, and never 'tends to'/'seems to'."
        )
        retry = _generate_once(client, post, block, nudge=nudge, voice_ex_block=voice_ex_block)
        if retry and len(_draft_problems(retry, avoid)) < len(problems):
            text = retry
    return text


def generate_drafts(client: Client, post: Post, count: int = 2, avoid_texts: list[str] | None = None,
                    voice_examples: list[str] | None = None) -> list[str]:
    """Generate `count` DIVERSE candidates. The 2nd deliberately takes a different shape
    and angle from the 1st (and avoids it), so the reviewer gets genuinely different
    options rather than two near-identical drafts. Each is self-corrected once.
    `voice_examples` are comments the team approved for this client — the learning loop's
    anchor for how she really sounds."""
    base_avoid = list(avoid_texts or [])
    voice_ex_block = _voice_examples_block(voice_examples)
    out: list[str] = []
    for i in range(max(1, count)):
        if not out:
            text = _one_candidate(client, post, base_avoid, shape_nudge="", voice_ex_block=voice_ex_block)
        else:
            # Candidate 2+: force a different shape/angle from the ones already produced.
            shape_nudge = (
                "IMPORTANT: make this a DIFFERENT KIND of comment from the option(s) already written "
                "below — a different shape (if that one was an observation, ask a genuine question; if it "
                "stated a view, react to a different specific detail instead) and a different opening. "
                "The two options must feel distinct, not two phrasings of the same thought."
            )
            text = _one_candidate(client, post, out + base_avoid, shape_nudge=shape_nudge, voice_ex_block=voice_ex_block)
        if text and text not in out:
            out.append(text)
    return out


def refine_draft(client: Client, post: Post, current_text: str, instruction: str) -> str:
    """Revise a single draft per an operator instruction (e.g. 'shorter', 'more personal')."""
    message = _client.with_options(max_retries=1, timeout=45.0).messages.create(
        model=settings.draft_model,
        max_tokens=800,
        extra_body={"thinking": {"type": "disabled"}},  # single-call refine — house style carries the AI-tell bans
        messages=[{
            "role": "user",
            "content": REFINE_PROMPT.format(
                name=client.name,
                voice=_voice_block(client),
                house_style=HOUSE_STYLE,
                benchmark=_benchmark_block(client),
                feedback=_feedback_block(client),
                content=post.content_snippet,
                current=current_text,
                instruction=instruction,
            ),
        }],
    )
    try:
        data = extract_json(message)
        revised = str(data["draft"])
    except (ValueError, KeyError):
        return current_text
    out = humanize_comments([revised], _voice_block(client))
    return _strip_negation(out[0] if out else revised)  # hard-enforce: no negation-as-a-device
