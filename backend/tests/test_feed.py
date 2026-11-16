"""R27 and R28 (#aitools-linkedin-account-managers, 10-11 Nov 2026).

R27, Umar: "very few comments for Nikolina" for 2-3 days, though all her prospects are marked.
R28, Baba: Noah's feed shows posts "completely different (have nothing to do with him)".

Fixtures stand in for Apify items and stored rows; the relevance scorer is faked. Nothing here
calls Apify, Azure or Supabase.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.jobs import discovery as J
from app.models import Client, Creator, CreatorClient, Draft, Post, WatchCreator
from app.routers import posts as P
from app.scraper import apify_client as A

ATTIA = "https://www.linkedin.com/in/peterattiamd/"


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Reposts: never ask for them, and drop the ones that arrive anyway ----------------------

def test_actor_input_asks_for_no_reposts(monkeypatch):
    monkeypatch.setattr(settings, "apify_input_json", '{"targetUrls": ["{url}"], "maxPosts": {limit}}')
    assert A._build_input(ATTIA, 1) == {"targetUrls": [ATTIA], "maxPosts": 1, "includeReposts": False}
    # An explicit setting in the env var still wins.
    monkeypatch.setattr(settings, "apify_input_json",
                        '{"targetUrls": ["{url}"], "maxPosts": {limit}, "includeReposts": true}')
    assert A._build_input(ATTIA, 1)["includeReposts"] is True


def _item(**over):
    item = {"type": "post", "linkedinUrl": "https://www.linkedin.com/posts/p-1",
            "content": "Zone 2 training and sleep, in that order.",
            "author": {"name": "Peter Attia", "linkedinUrl": "https://www.linkedin.com/in/peterattiamd"},
            "postedAt": {"date": "2026-11-09T10:00:00Z"}}
    item.update(over)
    return item


def test_normaliser_flags_plain_reposts_but_not_quote_posts():
    assert A._normalise(_item())["is_repost"] is False
    assert A._normalise(_item(header={"text": "Peter Attia reposted this"}))["is_repost"] is True
    assert A._normalise(_item(isRepost=True))["is_repost"] is True
    assert A._normalise(_item(content="", repost={"content": "someone else's post"}))["is_repost"] is True
    # A quote post: his own words over someone else's post. His words, so it stays.
    assert A._normalise(_item(repost={"content": "someone else's post"}))["is_repost"] is False


def _raw(author_name, author_url, url="https://www.linkedin.com/posts/p-1", text=None, **extra):
    return {"author_name": author_name, "author_profile_url": author_url, "post_url": url,
            "content_snippet": text or ("Sleep, zone 2 and protein are the levers that matter for "
                                        "healthspan, and the evidence for each keeps getting better."),
            "posted_at": now() - timedelta(days=1), "engagement": {}, **extra}


@pytest.fixture
def tracked(db):
    db.add(Client(id=1, name="Noah Laith", specialty="longevity", topics=[]))
    db.add(Creator(id=1, name="Peter Attia", profile_url=ATTIA, kind="creator"))
    db.add(CreatorClient(creator_id=1, client_id=1))
    db.commit()
    return db


def test_someone_elses_post_from_a_tracked_profile_is_recognised(tracked):
    db = tracked
    other = _raw("Jane Doe", "https://www.linkedin.com/in/jane-doe-123?miniProfileUrn=x")
    assert J.is_someone_elses_post(db, ATTIA, other)
    # His own post, his handle.
    assert not J.is_someone_elses_post(db, ATTIA, _raw("Peter Attia", "https://www.linkedin.com/in/peterattiamd"))
    # His own post under a new handle (the Eric Verdin case): same name, so kept.
    assert not J.is_someone_elses_post(db, ATTIA, _raw("Peter Attia, MD", "https://www.linkedin.com/in/peter-attia-md"))
    # Can't tell (member-ID URL, or nothing on file): kept, never guessed away.
    assert not J.is_someone_elses_post(db, ATTIA, _raw("Jane Doe", "https://www.linkedin.com/in/ACoAABxyz"))
    assert not J.is_someone_elses_post(db, "https://www.linkedin.com/in/unknown/", other)
    # Flagged by the actor.
    assert J.is_someone_elses_post(db, ATTIA, _raw("Peter Attia", "", is_repost=True))


class Scorer:
    def __init__(self, *scores):
        self.scores = list(scores)
        self.calls = 0

    def __call__(self, client, post):
        self.calls += 1
        s = self.scores.pop(0) if self.scores else 0.8
        return (None, "relevance scoring failed — not scored yet", "") if s is None else (s, "fits", "gist")


def test_a_repost_never_reaches_the_feed(tracked, monkeypatch):
    db = tracked
    scorer = Scorer(0.9)
    monkeypatch.setattr(J, "score_post", scorer)
    J._save_and_process(db, db.get(Client, 1), ATTIA,
                        _raw("Jane Doe", "https://www.linkedin.com/in/jane-doe-123", text="Our bakery turns ten!"))
    assert db.query(Post).count() == 0 and scorer.calls == 0  # not saved, and no paid call


# --- Unscored posts: scored before saving, and re-scored when they come back ----------------

def test_post_is_saved_with_its_score(tracked, monkeypatch):
    db = tracked
    monkeypatch.setattr(J, "score_post", Scorer(0.2))
    J._save_and_process(db, db.get(Client, 1), ATTIA, _raw("Peter Attia", ATTIA))
    assert db.query(Post).one().relevance_score == 0.2


def test_failed_score_is_retried_when_the_post_comes_back(tracked, monkeypatch):
    """An unscored post skips the relevance floor and nothing re-scored it, so one failed call left
    an off-topic post in the feed for good."""
    db = tracked
    scorer = Scorer(None, 0.1)
    monkeypatch.setattr(J, "score_post", scorer)
    c = db.get(Client, 1)
    J._save_and_process(db, c, ATTIA, _raw("Peter Attia", ATTIA))
    assert db.query(Post).one().relevance_score is None
    J._save_and_process(db, c, ATTIA, _raw("Peter Attia", ATTIA))  # next fetch / webhook retry
    assert db.query(Post).one().relevance_score == 0.1
    J._save_and_process(db, c, ATTIA, _raw("Peter Attia", ATTIA))  # scored now: no further calls
    assert scorer.calls == 2


# --- Two-feeds-per-post cap: a row hidden from its own client takes no slot -----------------

def _feed(db, client_id):
    return {p.post_url for p in db.query(Post).filter(*P._visible_conditions(db, client_id, 14)).all()}


@pytest.fixture
def shared_post(db):
    for i, name in ((1, "Dr. Joe Raffaele"), (2, "Nikolina Lauc"), (3, "Gordan Lauc")):
        db.add(Client(id=i, name=name, specialty="longevity", topics=[]))
    db.commit()

    def add(client_id, score, priority=False, pid=None):
        db.add(Post(client_id=client_id, source_type="creator", source_ref=ATTIA,
                    post_url="https://www.linkedin.com/posts/p-1", content_snippet="x",
                    posted_at=now() - timedelta(days=1), relevance_score=score, is_priority=priority,
                    language="en", dismissed=False))
        db.commit()
    return add


def test_priority_row_below_its_own_bar_does_not_take_a_slot(db, shared_post):
    shared_post(1, 0.2, priority=True)  # Joe: priority, but 2/10, so hidden from Joe himself
    shared_post(3, 0.8)
    shared_post(2, 0.7)
    assert _feed(db, 1) == set()                    # hidden from Joe (below the 3/10 priority bar)
    assert _feed(db, 3) and _feed(db, 2)            # so both slots go to clients who can comment


def test_priority_row_he_can_use_still_wins_a_slot(db, shared_post):
    shared_post(1, 0.5, priority=True)
    shared_post(3, 0.8)
    shared_post(2, 0.7)
    assert _feed(db, 1) and _feed(db, 3)
    assert _feed(db, 2) == set()                    # third-best still loses: the cap itself is unchanged


def test_below_bar_row_with_work_keeps_its_slot(db, shared_post):
    shared_post(1, 0.2, priority=True)
    joe_row = db.query(Post).filter(Post.client_id == 1).one()
    db.add(Draft(post_id=joe_row.id, text="drafted before the bar existed", status="drafted"))
    db.commit()
    shared_post(3, 0.8)
    shared_post(2, 0.7)
    assert _feed(db, 1) and _feed(db, 3)
    assert _feed(db, 2) == set()


# --- The read-only queue report (how to confirm R27 on live data) --------------------------

def test_queue_report_says_where_posts_went(db, shared_post):
    from app.jobs.queue_report import report
    db.add(Creator(id=1, name="Peter Attia", profile_url=ATTIA, kind="creator"))
    db.add(Creator(id=2, name="A Prospect", profile_url="https://www.linkedin.com/in/someone/", kind="prospect"))
    db.add(CreatorClient(creator_id=1, client_id=2))
    db.add(CreatorClient(creator_id=2, client_id=2))
    db.commit()
    shared_post(1, 0.9, priority=True)
    shared_post(3, 0.8)
    shared_post(2, 0.7)
    db.add(Post(client_id=2, source_type="creator", source_ref=ATTIA, post_url="https://www.linkedin.com/posts/p-2",
                content_snippet="x", posted_at=now() - timedelta(days=2), relevance_score=0.1, language="en"))
    db.commit()
    r = report(db, db.get(Client, 2))
    assert r["posts_stored_in_window"] == 2
    assert r["where_they_went"] == {"lost to the two-feeds-per-post cap": 1, "below the relevance bar": 1}
    assert r["cap_slots_taken_by"] == {"Dr. Joe Raffaele (priority)": 1, "Gordan Lauc": 1}
    assert r["profiles"]["assigned_creators"] == 1
    assert r["profiles"]["assigned_but_not_fetched"] == ["A Prospect (prospect)"]
