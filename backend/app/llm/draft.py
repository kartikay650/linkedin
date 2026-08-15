import re
from concurrent.futures import ThreadPoolExecutor

import anthropic

from app.config import settings
from app.llm.humanize import humanize_comments
from app.llm.style import HOUSE_STYLE, check_violations, has_negation_device
from app.llm.utils import extract_json
from app.models import Client, Post

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _call(model: str, prompt: str, max_tokens: int = 800, timeout: float = 45.0):
    """One thinking-disabled message call (pinned SDK). Used by every step of the reasoning
    drafter — brief, plan, draft, critique, tighten."""
    return _client.with_options(max_retries=1, timeout=timeout).messages.create(
        model=model, max_tokens=max_tokens, extra_body={"thinking": {"type": "disabled"}},
        messages=[{"role": "user", "content": prompt}],
    )


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
            cand = str(extract_json(_call(settings.draft_model, STRIP_NEGATION_PROMPT.format(text=out), 400, 30.0)).get("text", "")).strip()
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
        "different sentence shape, a different angle. Do not reuse their phrasings.\n" + lines + "\n=== END ==="
    )


def _siblings_block(texts: list[str] | None, name: str) -> str:
    """Comments OTHER profiles already made on this SAME post. Shown so this client's reply takes a
    genuinely different angle (grounded in her own expertise) instead of echoing another profile —
    the fix for 'two profiles get near-identical comments on the same post'."""
    ex = [t.strip() for t in (texts or []) if t and t.strip()][:8]
    if not ex:
        return ""
    lines = "\n".join(f"- {t}" for t in ex)
    return (
        "=== OTHER PROFILES ALREADY COMMENTED ON THIS EXACT POST ===\n"
        f"These were written for OTHER people on this same post. {name}'s comment MUST take a genuinely "
        "different angle, grounded in HER own expertise — not a reword or the same point as these:\n"
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
    if profile["q_rate"] >= 0.25:
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
    if profile:
        fw = _first_word(text)
        low = (text or "").lower()
        if fw and fw in profile["overused_openers"]:
            problems.append(f"opens with the over-used word '{fw}'")
        if profile["curious_rate"] >= 0.06 and "curious" in low:
            problems.append("uses 'Curious', which is over-used right now")
        if profile["q_rate"] >= 0.25 and _is_question(text):
            problems.append("is a question, and questions are over-used right now")
    return problems


# --- Reasoning drafter -------------------------------------------------------
# Instead of hand-coded heuristics deciding what to say, the model REASONS per-post about how
# the post should be answered — engage a real argument (even under a personal/novelty hook) vs
# honour a genuinely human moment — grounds any substance in the client's OWN material (so it's
# never invented), drafts to that plan, and self-critiques against it. The self-aware
# anti-repetition memory, humanizer, negation strip, and violation/length guardrails all still
# run around it. See the "reasoning, not a flag" design (2026-08).

_BRIEF_PROMPT = """Distill what {name} actually knows and believes into a tight brief a writer can use to add \
substance to comments. Use ONLY the material below — NEVER invent facts, studies, numbers, or positions she has \
not expressed. If it is not in the material, leave it out.
{material}
Return 6-10 short bullet lines: her core positions and the specific points she can credibly make. Plain language, no preamble."""


def _expertise_brief(client: Client, voice_examples: list[str] | None) -> str:
    """A grounded brief of what the client actually knows/believes, distilled ONLY from their own
    material (viewpoints, key messages, audience, voice samples, guardrails, approved comments) so
    the drafter can be substantive WITHOUT inventing. Generated on the fly on the fast model and
    reused across this post's candidates (garbage-in guard: nothing here that isn't in her material,
    and the provenance check still backstops the final draft)."""
    mats = []
    for label, val in (
        ("VIEWPOINTS", client.viewpoints), ("KEY MESSAGES", client.key_messages),
        ("AUDIENCE", client.audience), ("HER OWN WORDS", client.voice_samples),
        ("GUARDRAILS", client.guardrails),
    ):
        if (val or "").strip():
            mats.append(f"{label}: {val.strip()[:2000]}")
    appr = [t.strip() for t in (voice_examples or []) if t and t.strip()][:8]
    if appr:
        mats.append("APPROVED COMMENTS: " + "\n".join(appr)[:1200])
    if not mats:
        return ""
    try:
        return _call(settings.relevance_model, _BRIEF_PROMPT.format(name=client.name, material="\n".join(mats)), 700, 30.0).content[0].text.strip()
    except Exception:
        return ""


_PLAN_PROMPT = """You are deciding how {name} should reply to a LinkedIn post. THINK IT THROUGH, then give a directive.

Her expertise (use ONLY if the reply should be substantive):
{brief}

Reason about THIS post:
1. What is the author actually DOING — making an argument/claim, sharing news or data, venting or being vulnerable, \
celebrating a milestone, or posting a motivational affirmation? Look PAST the opening hook or novelty framing to the real purpose.
2. Do they INVITE a substantive/expert response, or is this a human moment where a clinical/biomarker reply would feel \
tone-deaf or salesy — even if the topic is technically in her field?
3. If OTHER profiles have already commented on this exact post (shown below), her take MUST be genuinely different \
from theirs and grounded in HER OWN distinct expertise — a different angle, not the same point reworded.
4. Given all that, what should she actually say — and what should she NOT do?
{siblings}
Return ONLY JSON:
{{"read": "2-3 sentences of your reasoning for points 1-4",
  "approach": "ONE directive telling the writer exactly how to respond: the tone AND what to engage. Be explicit if she should NOT bring science/biomarkers/data here, and how her angle differs from any other profiles above.",
  "core": "the post's main point if it makes one, else empty string",
  "can_add": ["if the reply should be substantive: 1-3 grounded points from her expertise (no invented facts); else empty"],
  "avoid": ["the hook/novelty/peripheral not to center on; include 'no clinical or biomarker talk' if this is a human moment"]}}

Post by {author}:
\"\"\"{content}\"\"\""""


def _plan(client: Client, post: Post, brief: str, siblings_block: str = "") -> dict:
    """The reasoning step: decide how THIS post should be answered — including taking a distinct angle
    from any other profiles that already commented on it. Falls back to an empty plan (drafter then
    leans on house style) if the call fails."""
    try:
        p = extract_json(_call(settings.draft_model,
            _PLAN_PROMPT.format(name=client.name, brief=(brief or "(no brief available)"),
                                siblings=(("\n" + siblings_block) if siblings_block else ""),
                                author=post.author_name, content=post.content_snippet), 700, 45.0))
    except Exception:
        p = {}
    if not isinstance(p, dict):
        p = {}
    for k, d in (("read", ""), ("approach", ""), ("core", ""), ("can_add", []), ("avoid", [])):
        p.setdefault(k, d)
    return p


def _rules_block(client: Client) -> str:
    """Only the HARD constraints (CTA rules + guardrails) — the knowledge itself lives in the brief."""
    parts = []
    if (client.cta_rules or "").strip():
        parts.append("CTA rules:\n" + client.cta_rules.strip())
    if (client.guardrails or "").strip():
        parts.append("Guardrails (hard rules):\n" + client.guardrails.strip())
    return ("=== HARD RULES ===\n" + "\n\n".join(parts) + "\n=== END ===") if parts else ""


_DRAFT_PROMPT = """You are writing ONE LinkedIn comment reply AS {name}. It must be indistinguishable from something she typed.

=== HOW SHE ACTUALLY WRITES (match exactly) ===
{voice}
=== END ===

{voice_examples}

=== HOW TO RESPOND HERE (follow this exactly) ===
{approach}
Core point of the post: {core}
What she could add (only if the approach calls for substance — otherwise ignore this): {can_add}
Do NOT center on / do NOT do: {avoid}
If (and ONLY if) the approach calls for substance, ground it in what she actually knows (never invent):
{brief}
=== END ===

{rules}

{house_style}

{feedback}

{memory}

The post she is replying to:
Author: {author}
\"\"\"
{content}
\"\"\"
{shape}
Write ONE reply that follows the approach exactly: if it says stay human, be warm and specific to what they said and bring \
NO science, data, or biomarkers; if it says engage the argument, add a grounded point in her voice. Always SHORT (one or two \
sentences, MAX 22 words), at most one claim, structurally different from her recent comments, and never the words "tends to" / "seems to". \
Respond ONLY with JSON: {{"drafts": ["your one reply"]}}"""


def _reason_generate_once(client: Client, post: Post, brief: str, plan: dict,
                          voice_ex_block: str, memory_block: str, shape: str) -> str:
    prompt = _DRAFT_PROMPT.format(
        name=client.name, voice=_voice_block(client), voice_examples=voice_ex_block,
        approach=plan.get("approach", ""), core=plan.get("core", ""),
        can_add="; ".join(plan.get("can_add") or []), avoid="; ".join(plan.get("avoid") or []),
        brief=(brief or "(none)"), rules=_rules_block(client), house_style=HOUSE_STYLE,
        feedback=_feedback_block(client), memory=memory_block,
        author=post.author_name, content=post.content_snippet, shape=("\n" + shape if shape else ""),
    )
    try:
        drafts = [str(d) for d in extract_json(_call(settings.draft_model, prompt, 800, 45.0))["drafts"] if str(d).strip()]
    except (ValueError, KeyError):
        return ""
    drafts = humanize_comments(drafts, _voice_block(client))
    drafts = [_strip_negation(d) for d in drafts]  # hard-enforce: no negation-as-a-device
    return drafts[0] if drafts else ""


_CRIT_PROMPT = ('Intended approach for this comment: "{approach}". The draft: "{d}". Does it FOLLOW that approach — '
                'right tone, engages the right thing, not tone-deaf, not shallow, not clinical/salesy where it should be '
                'human, not centred on a peripheral hook? Respond ONLY with JSON: {{"ok": true or false, "fix": "short instruction if not ok, else empty"}}')

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


def _wc(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text or ""))


def _hard_problems(text: str, avoid: list[str], allow_formula: bool) -> list[str]:
    """House-style/length/repetition violations worth a regenerate. Drops the 'before symptoms'
    formula flag when the post itself is about pre-diagnosis action (then it's on-topic)."""
    probs = _draft_problems(text, avoid, None)
    if allow_formula:
        probs = [p for p in probs if "shows up" not in p]
    return probs


def _tighten(text: str, allow_formula: bool) -> str:
    """HARD length/formula guardrail: if a draft runs long or uses a banned construction, force a
    tight rewrite; keep it only if genuinely cleaner. Runs at most twice."""
    for _ in range(2):
        v = check_violations(text)
        if allow_formula:
            v = [x for x in v if "shows up" not in x]
        if not (any(("wordy" in x or "sentences" in x or "hedge" in x or "shows up" in x) for x in v) or _wc(text) > 26):
            break
        extra = "" if allow_formula else ' Do NOT use the vague "X before symptoms/diagnosis/a scan" template.'
        try:
            nt = str(extract_json(_call(settings.draft_model,
                f'Rewrite in ONE or two short sentences, MAX 22 words, keeping the exact point and her voice. '
                f'Remove any "tends to"/"seems to".{extra} Comment: "{text}". Respond ONLY with JSON: {{"text": "..."}}',
                300, 30.0)).get("text", "")).strip()
        except Exception:
            break
        nv = check_violations(nt)
        if allow_formula:
            nv = [x for x in nv if "shows up" not in x]
        if nt and len(nv) <= len(v) and _wc(nt) <= _wc(text):
            text = nt
        else:
            break
    return text


def _reason_candidate(client: Client, post: Post, brief: str, plan: dict, avoid: list[str],
                      voice_ex_block: str, memory_block: str, shape: str) -> str:
    """One reply: draft to the plan, self-critique against the approach + rule-gate, regenerate once
    if off, then hard-tighten length/formula."""
    allow = _prediagnosis(post)
    text = _reason_generate_once(client, post, brief, plan, voice_ex_block, memory_block, shape)
    if not text:
        return ""
    try:
        crit = extract_json(_call(settings.relevance_model, _CRIT_PROMPT.format(approach=plan.get("approach", ""), d=text), 200, 25.0))
    except Exception:
        crit = {}
    if not isinstance(crit, dict):
        crit = {}
    probs = _hard_problems(text, avoid, allow)
    too_long = _wc(text) > 26
    if crit.get("ok") is False or probs or too_long:
        fix = ("Fix: " + str(crit.get("fix", "")) + ". ") if crit.get("ok") is False else ""
        if probs:
            fix += "Also fix: " + "; ".join(probs) + ". "
        if too_long:
            fix += "Make it MAX 20 words. "
        retry = _reason_generate_once(client, post, brief, plan, voice_ex_block, memory_block, (shape + " " + fix).strip())
        if retry:
            text = retry
    return _tighten(text, allow)


def generate_drafts(client: Client, post: Post, count: int = 2, avoid_texts: list[str] | None = None,
                    voice_examples: list[str] | None = None, global_texts: list[str] | None = None,
                    sibling_texts: list[str] | None = None) -> list[str]:
    """Generate `count` DIVERSE candidates via the reasoning drafter: distil a grounded brief of what
    the client actually knows, REASON about how this specific post should be answered (engage a real
    argument — even under a personal/novelty hook — vs honour a human moment), draft to that plan
    grounded in her material, and self-critique against it. The self-aware anti-repetition memory
    (from `avoid_texts` + `global_texts`), humanizer, negation strip, and violation/length guardrails
    all still run. `voice_examples` = comments the team approved (learning-loop voice anchor + part of
    the grounding brief). `sibling_texts` = comments OTHER profiles already made on THIS SAME post, so
    this client takes a genuinely different, self-tailored angle instead of echoing them. Candidates
    run in parallel to stay well under the serverless time budget."""
    base_avoid = list(avoid_texts or [])
    brief = _expertise_brief(client, voice_examples)
    siblings_block = _siblings_block(sibling_texts, client.name)
    plan = _plan(client, post, brief, siblings_block)
    voice_ex_block = _voice_examples_block(voice_examples)
    profile = output_profile(base_avoid + list(global_texts or []))
    memory_block = "\n\n".join(b for b in (_self_awareness_block(profile), siblings_block, _avoid_block(base_avoid)) if b)
    # Reused-opener gate also considers other profiles' comments on this post, so a second profile
    # can't open the same way as the first.
    gate_avoid = base_avoid + [t.strip() for t in (sibling_texts or []) if t and t.strip()]
    # Option 1 is free; option 2+ must take a clearly different opening/angle (still on the approach).
    n = max(1, count)
    shapes = [""] + ["Take a clearly different opening and angle from the other option(s), still following the approach above."] * (n - 1)

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
    return out


def refine_draft(client: Client, post: Post, current_text: str, instruction: str) -> str:
    """Revise a single draft per an operator instruction (e.g. 'shorter', 'more personal')."""
    try:
        data = extract_json(_call(settings.draft_model, REFINE_PROMPT.format(
            name=client.name, voice=_voice_block(client), house_style=HOUSE_STYLE,
            benchmark=_benchmark_block(client), feedback=_feedback_block(client),
            content=post.content_snippet, current=current_text, instruction=instruction), 800, 45.0))
        revised = str(data["draft"])
    except (ValueError, KeyError):
        return current_text
    out = humanize_comments([revised], _voice_block(client))
    return _strip_negation(out[0] if out else revised)  # hard-enforce: no negation-as-a-device
