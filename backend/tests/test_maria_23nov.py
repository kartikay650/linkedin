"""Maria's feedback, 23 Nov 2026 (#aitools-linkedin-account-managers, Baba's 10 Nov thread).

1. The buttons sometimes return almost the same comment. Production 13-23 Nov: about 1 press in 8
   of Warmer / More conversational / More personality changed under 30% of the words, and short
   comments flipped between the same two versions.
3. No semicolons, no colon-led sentences, and no "really matters" / "the fact that" /
   "I'll be watching" / "what stands out".

The model is faked (FakeLLM): what is tested is what reaches it and what is done with its answer.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.llm import draft as D
from app.llm.style import check_violations, plain_punctuation
from app.models import Client, Draft, Post, TweakEvent
from app.routers import posts as P
from tests.conftest import FakeLLM

POST_TEXT = ("Our longevity protocol now puts sleep ahead of every supplement. The dosing table for "
             "magnesium is in the comments.")
CURRENT = "Sleep comes first in this plan, and the data in the post backs it."
SMALL = "Sleep comes first in this plan, and the data in the post supports it."
BIG = "Putting sleep ahead of every supplement is something anyone can start tonight, which I love."
EARLIER = "Sleep before supplements is the order I would pick too, honestly."


def reply(text, not_done=""):
    return json.dumps({"draft": text, "not_done": not_done})


@pytest.fixture
def client_post():
    c = Client(id=1, name="Nikolina Lauc", specialty="glycobiology", topics=[], viewpoints="",
               voice_guide="", voice_samples="", benchmark_examples="")
    c.feedback = []
    p = Post(id=1, client_id=1, source_type="creator", source_ref="https://www.linkedin.com/in/x/",
             post_url="https://www.linkedin.com/posts/x-1", content_snippet=POST_TEXT)
    return c, p


@pytest.fixture
def fake(monkeypatch):
    def install(*replies):
        llm = FakeLLM(replies)
        monkeypatch.setattr(D, "_call", llm)
        monkeypatch.setattr(D, "humanize_comments", lambda texts, voice, keep="": list(texts))
        return llm
    return install


def test_fixtures_are_clean_comments():
    for t in (CURRENT, SMALL, BIG, EARLIER):
        assert check_violations(t) == [], t


# --- 3. Semicolons, colon-led sentences and the phrases -------------------------------------

@pytest.mark.parametrize("text,kind", [
    ("The research is promising; the challenge now is getting it into clinics.", "semicolon"),
    ("This highlights an important point: longevity research needs to focus on prevention.",
     "colon-led sentence"),
    ("One thing stands out here: the importance of making science accessible.", "colon-led sentence"),
    ("Access really matters here, especially for older patients.", "banned phrase: 'really matters'"),
    ("The fact that it held up in older adults is encouraging.", "banned phrase: 'the fact that'"),
    ("That’s the part I’ll be watching in the next trial.", "banned phrase: 'i'll be watching'"),
    ("What stands out to me is the sample size in the second cohort.",
     "banned phrase: 'what stands out'"),
])
def test_marias_patterns_are_violations(text, kind):
    assert kind in check_violations(text)


@pytest.mark.parametrize("text", [
    "We started the clinic at 10:30 that morning, with every patient fasted.",
    "The protocol is on their site at https://example.org/protocol for anyone who wants it.",
])
def test_times_and_links_are_not_colon_sentences(text):
    assert "colon-led sentence" not in check_violations(text)


@pytest.mark.parametrize("before,after", [
    ("The research is promising; the challenge now is getting it into clinics.",
     "The research is promising, the challenge now is getting it into clinics."),
    ("Is it real?; maybe not", "Is it real? maybe not"),
    ("a ;b; c", "a, b, c"),
    # Review, 24 Nov: a capital would turn mRNA into MRNA; an entity is not punctuation.
    ("It took two doses; mRNA platforms will make that faster.",
     "It took two doses, mRNA platforms will make that faster."),
    ("R&amp;D budgets matter; so does follow-through.", "R&amp;D budgets matter, so does follow-through."),
    ("No semicolon here, just a comma.", "No semicolon here, just a comma."),
])
def test_plain_punctuation_turns_semicolons_into_commas(before, after):
    assert plain_punctuation(before) == after


def test_plain_punctuation_never_creates_stacked_statements():
    """Review, 24 Nov: a full stop made "X. Y" with no comma, the shape the owner rejects most."""
    from app.llm.style import has_stacked_statements
    out = plain_punctuation("Sleep is underrated; most clinics never ask about it.")
    assert not has_stacked_statements(out) and check_violations(out) == []


@pytest.mark.parametrize("text", [
    'Her book "Menopause: The Hidden Years" is on my desk, and it shows.',
    "Seeing you at HLTH Europe 2026: Amsterdam was the right place for this, honestly.",
    "Somewhat stands out to me as the right call, given the cohort.",
    "R&amp;D budgets are where this gets decided, in the end.",
])
def test_titles_entities_and_partial_words_are_not_flagged(text):
    assert check_violations(text) == []


def test_a_semicolon_alone_costs_no_retry(client_post, fake):
    """plain_punctuation fixes it for free; FakeLLM would raise on a second call."""
    c, p = client_post
    fake(reply("Sleep comes first in this plan; the data in the post backs it, warmly."))
    text, _ = D.refine_draft(c, p, CURRENT, "keep it but say it differently")
    assert text == "Sleep comes first in this plan, the data in the post backs it, warmly."


def test_typed_request_can_still_get_her_comment_back_on_retry(client_post, fake):
    """Review, 24 Nov: the size-check refusals must not reach typed requests."""
    c, p = client_post
    certain = "This definitely proves that sleep comes first in this plan, and the data backs it."
    fake(reply(certain), reply(CURRENT))
    text, _ = D.refine_draft(c, p, CURRENT, "make it firmer", earlier=[EARLIER])
    assert text == CURRENT


def test_house_style_tells_the_drafter_about_them():
    from app.llm.style import HOUSE_STYLE
    assert "semicolons" in HOUSE_STYLE and "colon" in HOUSE_STYLE
    assert '"really matters"' in HOUSE_STYLE


# --- 1. Buttons that return almost the same comment ------------------------------------------

def test_word_change():
    assert D.word_change(CURRENT, CURRENT) == 0.0
    assert D.word_change(CURRENT, SMALL) < 0.3
    assert D.word_change(CURRENT, BIG) > 0.5


def test_change_too_small_only_judges_the_style_buttons_and_shorter():
    assert D.change_too_small("warmer", SMALL, CURRENT)
    assert D.change_too_small("conversational", SMALL, CURRENT)
    assert D.change_too_small("personality", SMALL, CURRENT)
    assert not D.change_too_small("warmer", BIG, CURRENT)
    # A version she already saw is "the same comment" however different it is from this one.
    assert D.change_too_small("warmer", EARLIER, CURRENT, earlier=[EARLIER])
    # Targeted edits: a small change is the right answer.
    for chip in (None, "remove_opinion", "no_question"):
        assert not D.change_too_small(chip, SMALL, CURRENT)
    assert D.change_too_small("shorter", SMALL, CURRENT)
    assert not D.change_too_small("shorter", "Sleep comes first, and the data backs it.", CURRENT)


def test_small_change_gets_one_retry_and_the_bigger_change_wins(client_post, fake):
    c, p = client_post
    llm = fake(reply(SMALL), reply(BIG))
    text, note = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["warmer"], chip="warmer")
    assert text == BIG and note == ""
    assert "changed only a few words" in llm.prompts[1]
    assert SMALL in llm.prompts[1]


def test_still_small_after_the_retry_is_shown_with_a_note(client_post, fake):
    c, p = client_post
    fake(reply(SMALL), reply(SMALL))
    text, note = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["conversational"], chip="conversational")
    assert text == SMALL
    assert D.TWEAK_SMALL in note


def test_flip_flop_back_to_an_earlier_version_is_not_shown(client_post, fake):
    """The short-comment ping-pong: the tool hands back the version she had two presses ago."""
    c, p = client_post
    llm = fake(reply(EARLIER), reply(EARLIER))
    text, note = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["personality"], chip="personality",
                                earlier=[EARLIER])
    assert text == CURRENT and note == D.TWEAK_SMALL
    assert EARLIER in llm.prompts[1] and "earlier versions" in llm.prompts[1]


def test_a_retry_that_returns_an_earlier_version_is_refused(client_post, fake):
    c, p = client_post
    fake(reply(SMALL), reply(EARLIER))
    text, note = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["warmer"], chip="warmer",
                                earlier=[EARLIER])
    assert text == SMALL and D.TWEAK_SMALL in note


def test_typed_request_makes_no_extra_call(client_post, fake):
    """Her own words may ask for one exact word: FakeLLM would raise on a second call."""
    c, p = client_post
    text, _ = (fake(reply(SMALL)), D.refine_draft(c, p, CURRENT, "say supports instead of backs"))[1]
    assert text == SMALL


def test_remove_opinion_small_edit_is_not_retried_for_size(client_post, fake):
    c, p = client_post
    fake(reply(SMALL))
    text, _ = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["remove_opinion"], chip="remove_opinion")
    assert text == SMALL


def test_button_wording_asks_for_more_than_a_word_or_two():
    for chip in ("conversational", "personality", "warmer"):
        assert "a word or two" in D.TWEAK_CHIPS[chip]


# --- The route: chip and earlier versions reach refine_draft --------------------------------

@pytest.fixture
def api(db, monkeypatch):
    db.add(Client(id=1, name="Nikolina Lauc", specialty="glycobiology", topics=[]))
    db.add(Post(id=1, client_id=1, source_type="creator", source_ref="https://www.linkedin.com/in/x/",
                post_url="https://www.linkedin.com/posts/x-1", content_snippet=POST_TEXT))
    db.add(Draft(id=1, post_id=1, text=CURRENT, original_text=EARLIER, status="drafted"))
    db.add(TweakEvent(client_id=1, post_id=1, draft_id=1, chip="warmer", before_text=EARLIER))
    db.commit()
    seen = {}

    def fake_refine(client, post, current, instruction, **ctx):
        seen.update(ctx)
        return BIG, ""

    monkeypatch.setattr(P, "refine_draft", fake_refine)
    monkeypatch.setattr(P, "_safety_pass", lambda client, post, text, docs, keep="", removed=None: (text, []))
    app = FastAPI()
    app.include_router(P.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), seen


def test_route_sends_the_chip_and_earlier_versions(api):
    http, seen = api
    assert http.post("/drafts/1/refine", json={"chip": "warmer"}).status_code == 200
    assert seen["chip"] == "warmer"
    assert seen["earlier"] == [EARLIER, EARLIER]


def test_route_with_typed_words_sends_no_chip(api):
    http, seen = api
    assert http.post("/drafts/1/refine", json={"chip": "warmer", "instruction": "keep it short"}
                     ).status_code == 200
    assert seen["chip"] is None


def test_shorter_retry_wins_by_being_shorter(client_post, fake):
    """A one-sentence comment goes through the rewrite path; the retry must cut more, not just
    change more."""
    c, p = client_post
    longer_but_different = ("Putting sleep ahead of every supplement in this plan is what the data in "
                            "the post backs, and it shows.")
    fake(reply(SMALL), reply(longer_but_different))
    text, note = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["shorter"], chip="shorter")
    assert text == SMALL and D.TWEAK_SMALL in note
    fake(reply(SMALL), reply("Sleep first, and the data backs it."))
    text, _ = D.refine_draft(c, p, CURRENT, D.TWEAK_CHIPS["shorter"], chip="shorter")
    assert text == "Sleep first, and the data backs it."


def test_no_question_can_return_the_first_version(client_post, fake):
    """The flip-flop refusal is for the style buttons only. 'No question' turning a question back
    into the statement the tool first wrote is exactly the job."""
    c, p = client_post
    question = "Does sleep come first in this plan because of the data in the post?"
    fake(reply(EARLIER))
    text, _ = D.refine_draft(c, p, question, D.TWEAK_CHIPS["no_question"], chip="no_question",
                             earlier=[EARLIER])
    assert text == EARLIER


def test_unquestion_fixes_a_semicolon_instead_of_failing(client_post, fake):
    c, p = client_post
    fake(json.dumps({"text": "Sleep comes first here; the data backs it, clearly."}))
    assert D._unquestion(c, "Does sleep come first here?") == "Sleep comes first here, the data backs it, clearly."
