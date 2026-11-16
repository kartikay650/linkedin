"""R25 and R26 (#aitools-linkedin-account-managers, 10 Nov 2026).

R25, Baba: Warmer/Shorter "don't give the results I want", and the "tell it how to change" box "often
ignores the changes I want to make". R26, Umar: "Remove opinion" pressed three times, the same comment
three times. The model is faked (FakeLLM); what is tested is what reaches it and what is done with
its answer.
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.llm import draft as D
from app.models import Client, Draft, Post, TweakEvent
from app.routers import posts as P
from tests.conftest import FakeLLM

POST_TEXT = ("Our longevity protocol now puts sleep ahead of every supplement. The dosing table for "
             "magnesium is in the comments.")
OPINION = ("Sleep should come first in any longevity plan, and the data here backs the people who "
           "already treat it that way.")
NEUTRAL = ("Sleep comes first in this plan, and the data in the post backs the people who already "
           "treat it that way.")


def reply(text, not_done=""):
    return json.dumps({"draft": text, "not_done": not_done})


@pytest.fixture
def client_post():
    c = Client(id=1, name="Noah Laith", specialty="longevity medicine", topics=[], viewpoints="",
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


# --- R25: what she types reaches the model --------------------------------------------------

def test_chip_and_typed_words_make_one_request():
    combined = D.tweak_instruction("warmer", "  keep the   sleep point ")
    assert combined.startswith(D.TWEAK_CHIPS["warmer"])
    assert combined.endswith("in the reviewer's own words: keep the sleep point")
    assert D.tweak_instruction("warmer", "") == D.TWEAK_CHIPS["warmer"]
    assert D.tweak_instruction(None, "focus on the dosing table") == "focus on the dosing table"
    assert D.tweak_instruction(None, "   ") == ""


def test_tweak_avoid_block_no_longer_demands_a_different_comment():
    recent = ["Magnesium timing gets less attention than it deserves."]
    first = D._avoid_block(recent)
    tweak = D._avoid_block(recent, tweak=True)
    # First drafts: byte-identical to before.
    assert first.startswith("=== RECENT COMMENTS ALREADY WRITTEN FOR THIS CLIENT — do NOT sound like these")
    assert "a different angle" in first
    # Tweak: only "don't borrow phrasings", and an explicit "change only what the reviewer asks".
    assert "different angle" not in tweak and "different opening word" not in tweak
    assert "change only what the reviewer asks" in tweak


def test_free_text_reaches_the_refine_prompt_with_the_tweak_avoid_block(client_post, fake):
    c, p = client_post
    llm = fake(reply("Putting sleep ahead of supplements is a choice plenty of clinicians make already, "
                     "and the dosing table makes it concrete."))
    text, _ = D.refine_draft(c, p, NEUTRAL, "focus on the dosing table",
                             avoid_texts=["Magnesium timing gets less attention than it deserves."])
    assert "dosing table" in text
    prompt = llm.prompts[0]
    assert "The reviewer's request for this comment: focus on the dosing table" in prompt
    assert "change only what the reviewer asks" in prompt
    assert "a different sentence shape, a different angle" not in prompt


def test_keeping_her_own_opening_is_not_a_gate_failure(client_post, fake):
    """A Tweak that keeps the opening she had used to be sent back to the model as "same opening as
    a recent comment", and the retry rewrote the start of a comment she asked to change elsewhere."""
    c, p = client_post
    revised = "Sleep comes first in this plan, and the magnesium table in the post makes it concrete."
    llm = fake(reply(revised))
    text, note = D.refine_draft(c, p, NEUTRAL, "mention the magnesium table",
                                avoid_texts=["Sleep comes first for most of my patients too."])
    assert text == revised and note == ""
    assert len(llm.prompts) == 1  # no retry


# --- R26: "Remove opinion" ------------------------------------------------------------------

def test_opinion_detector():
    assert D.opinion_phrases(OPINION) == ["should"]
    assert D.opinion_phrases("I think the key point is sleep, and it will change how clinics work.") == [
        "i think", "the key point", "will change"]
    assert D.opinion_phrases(NEUTRAL) == []
    assert D._wants_no_opinion(D.TWEAK_CHIPS["remove_opinion"])
    assert D._wants_no_opinion("drop my opinion please") and D._wants_no_opinion("keep it neutral")
    assert not D._wants_no_opinion(D.TWEAK_CHIPS["warmer"])


def test_remove_opinion_that_comes_back_unchanged_is_retried_with_the_phrase_named(client_post, fake):
    c, p = client_post
    # The model decides there is "no opinion" and hands the comment back, as it did for Umar.
    llm = fake(reply(OPINION, "There is no opinion in this comment to remove."), reply(NEUTRAL))
    text, note = D.refine_draft(c, p, OPINION, D.TWEAK_CHIPS["remove_opinion"])
    assert text == NEUTRAL
    assert len(llm.prompts) == 2
    assert 'own view: "should"' in llm.prompts[1]
    assert not D.tweak_unchanged(text, OPINION)


def test_remove_opinion_never_accepts_a_retry_with_more_opinion(client_post, fake):
    c, p = client_post
    worse = "I think sleep should come first, and the key point is the data here."
    fake(reply(OPINION), reply(worse))
    text, _ = D.refine_draft(c, p, OPINION, D.TWEAK_CHIPS["remove_opinion"])
    assert text == OPINION  # unchanged, so the route shows a note instead of the same comment


def test_remove_opinion_noop_note_names_what_is_left():
    note = D.tweak_noop_note("remove_opinion", D.TWEAK_CHIPS["remove_opinion"], OPINION, "")
    assert '"should"' in note and "No opinion found" not in note
    assert D.tweak_noop_note("remove_opinion", D.TWEAK_CHIPS["remove_opinion"], NEUTRAL, "") == \
        D.TWEAK_NOOP["remove_opinion"]


def test_failed_model_call_is_a_failure_not_the_same_comment(client_post, fake):
    c, p = client_post
    fake("", "")
    assert D.refine_draft(c, p, OPINION, D.TWEAK_CHIPS["remove_opinion"]) == ("", "")


# --- The routes: chip + typed text, and Different angle with a focus ------------------------

@pytest.fixture
def api(db, monkeypatch):
    db.add(Client(id=1, name="Noah Laith", specialty="longevity", topics=[]))
    db.add(Post(id=1, client_id=1, source_type="creator", source_ref="https://www.linkedin.com/in/x/",
                post_url="https://www.linkedin.com/posts/x-1", content_snippet=POST_TEXT))
    db.add(Draft(id=1, post_id=1, text=OPINION, original_text=OPINION, status="drafted"))
    db.commit()
    seen = {}

    def fake_refine(client, post, current, instruction, **ctx):
        seen["refine"] = instruction
        return NEUTRAL, ""

    def fake_angle(client, post, taken, focus="", **ctx):
        seen["focus"] = focus
        return "The magnesium table in the post is the part a patient can act on tonight."

    monkeypatch.setattr(P, "refine_draft", fake_refine)
    monkeypatch.setattr(P, "angle_draft", fake_angle)
    monkeypatch.setattr(P, "shorten_draft", lambda *a, **k: pytest.fail("Shorter with typed words "
                                                                          "must not pick a sentence"))
    monkeypatch.setattr(P, "_safety_pass", lambda client, post, text, docs, keep="", removed=None: (text, []))
    app = FastAPI()
    app.include_router(P.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app), seen


def test_route_chip_carries_the_typed_words(api, db):
    http, seen = api
    r = http.post("/drafts/1/refine", json={"chip": "warmer", "instruction": "keep the sleep point"})
    assert r.status_code == 200, r.text
    assert seen["refine"] == D.tweak_instruction("warmer", "keep the sleep point")
    ev = db.query(TweakEvent).one()
    assert (ev.chip, ev.instruction) == ("warmer", "keep the sleep point")


def test_route_shorter_with_typed_words_goes_through_refine(api):
    http, seen = api
    r = http.post("/drafts/1/refine", json={"chip": "shorter", "instruction": "drop the data clause"})
    assert r.status_code == 200, r.text
    assert "drop the data clause" in seen["refine"]


def test_route_chip_alone_still_works(api):
    http, seen = api
    assert http.post("/drafts/1/refine", json={"chip": "remove_opinion"}).status_code == 200
    assert seen["refine"] == D.TWEAK_CHIPS["remove_opinion"]


def test_route_angle_takes_the_typed_focus(api):
    http, seen = api
    assert http.post("/drafts/1/angle", json={"instruction": "the magnesium table"}).status_code == 200
    assert seen["focus"] == "the magnesium table"
    # The dashboard's old call (no body) still works.
    assert http.post("/drafts/1/angle").status_code == 200
    assert seen["focus"] == ""


def test_angle_focus_reaches_the_prompt(client_post, monkeypatch):
    c, p = client_post
    shapes = []
    monkeypatch.setattr(D, "_draft_setup", lambda *a, **k: ("", {}, "", "", []))
    monkeypatch.setattr(D, "_reason_generate_once",
                        lambda client, post, brief, plan, vx, mem, shape: shapes.append(shape) or
                        "The magnesium table in the post is the part a patient can act on tonight.")
    D.angle_draft(c, p, [OPINION], focus="the magnesium table")
    assert 'which angle she wants: "the magnesium table"' in shapes[0]
