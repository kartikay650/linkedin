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


# --- No feed cap; each card names the other clients already on that post --------------------
# Lara, 20 Nov 2026: show every relevant post to every client and let the account manager decide,
# with a label when other clients already commented. Replaces the two-feeds-per-post cap.

URL = "https://www.linkedin.com/posts/peterattiamd_sleep-activity-7520308138625953793-AN9B"


def _feed(db, client_id):
    return {p.post_url for p in db.query(Post).filter(*P._visible_conditions(db, client_id, 14)).all()}


@pytest.fixture
def shared_post(db):
    for i, name in ((1, "Dr. Joe Raffaele"), (2, "Nikolina Lauc"), (3, "Gordan Lauc"), (4, "Noah Laith")):
        db.add(Client(id=i, name=name, specialty="longevity", topics=[]))
    db.commit()

    def add(client_id, score=0.7, priority=False, url=URL, status=None, text="x", author=ATTIA):
        p = Post(client_id=client_id, source_type="creator", source_ref=ATTIA, post_url=url,
                 author_profile_url=author, content_snippet=text, posted_at=now() - timedelta(days=1), relevance_score=score,
                 is_priority=priority, language="en", dismissed=False)
        db.add(p)
        db.commit()
        if status:
            db.add(Draft(post_id=p.id, text="a comment", status=status))
            db.commit()
        return p
    return add


def _card(db, client_id):
    (p,) = P._paged_posts(db, client_id, "all", 14, 60, 0)
    return p


def test_a_post_wanted_by_many_clients_reaches_all_of_them(db, shared_post):
    shared_post(1, 0.9, priority=True)
    for c in (2, 3, 4):
        shared_post(c, 0.5)
    assert all(_feed(db, c) == {URL} for c in (1, 2, 3, 4))   # the cap would have left 3 and 4 out


def test_the_relevance_bar_still_applies_per_client(db, shared_post):
    shared_post(1, 0.9)
    shared_post(2, 0.3)                                      # 3/10, below the bar of 4
    shared_post(3, 0.2, priority=True)                       # 2/10, below even the priority bar of 3
    assert _feed(db, 1) == {URL} and _feed(db, 2) == set() and _feed(db, 3) == set()


def test_card_names_other_clients_that_posted_or_approved(db, shared_post):
    shared_post(1)
    shared_post(2, status="posted")
    shared_post(3, status="approved")
    shared_post(4, status="drafted")                         # a draft nobody approved is not shown
    card = _card(db, 1)
    assert card.also_posted_by == ["Nikolina Lauc"]
    assert card.also_approved_for == ["Gordan Lauc"]


def test_own_comment_is_not_listed_and_posted_beats_approved(db, shared_post):
    mine = shared_post(1, status="posted")
    other = shared_post(2, status="posted")
    db.add(Draft(post_id=other.id, text="second version", status="approved"))
    db.commit()
    card = _card(db, 1)
    assert card.id == mine.id
    assert card.also_posted_by == ["Nikolina Lauc"] and card.also_approved_for == []


def test_same_post_under_an_edited_slug_still_matches(db, shared_post):
    shared_post(1)
    shared_post(2, url=URL.replace("_sleep-", "_sleep-and-ageing-").replace("AN9B", "EVjr"), status="posted")
    assert _card(db, 1).also_posted_by == ["Nikolina Lauc"]


def test_a_different_post_by_the_same_author_does_not_match(db, shared_post):
    shared_post(1)
    shared_post(2, url=URL.replace("7520308138625953793", "7520308138625953999"), status="posted")
    assert _card(db, 1).also_posted_by == []


TEXT = "Sleep is the most underrated longevity intervention we have, and here is what the data says."


def test_activity_and_ugcpost_urls_of_one_post_match_on_author_and_text(db, shared_post):
    # Seen in production: the scraper gave one client the activity id and another the ugcPost id.
    shared_post(1, text=TEXT)
    shared_post(2, url=URL.replace("activity-7520308138625953793", "ugcPost-7520308130000000000"),
                text=TEXT, status="posted")
    assert _card(db, 1).also_posted_by == ["Nikolina Lauc"]


def test_same_hashtag_slug_but_different_text_is_a_different_post(db, shared_post):
    # 79 slugs in production are shared by different posts (authors reuse hashtag slugs).
    shared_post(1, text=TEXT)
    shared_post(2, url=URL.replace("7520308138625953793", "7520308138625953999"),
                text="A completely different post about protein intake and muscle, with its own data.",
                status="posted")
    assert _card(db, 1).also_posted_by == []


def test_same_text_from_a_different_author_is_a_different_post(db, shared_post):
    shared_post(1, text=TEXT)
    shared_post(2, url=URL.replace("7520308138625953793", "7520308138625953999"), text=TEXT,
                author="https://www.linkedin.com/in/someone-else/", status="posted")
    assert _card(db, 1).also_posted_by == []


def test_text_with_like_wildcards_matches_exactly(db, shared_post):
    odd = "50% of adults_over 40 sleep < 6h \\ that is the headline from the new cohort data today"
    shared_post(1, text=odd)
    shared_post(2, url=URL.replace("activity-7520308138625953793", "ugcPost-7520308130000000000"),
                text=odd, status="posted")
    shared_post(3, url=URL.replace("activity-7520308138625953793", "ugcPost-7520308130000000001"),
                text=odd.replace("% of", "X of").replace("_", "Y"), status="posted")
    assert _card(db, 1).also_posted_by == ["Nikolina Lauc"]


def test_digits_inside_a_longer_number_do_not_match(db, shared_post):
    shared_post(1)
    shared_post(2, url="https://www.linkedin.com/posts/someone-else_x-activity-17520308138625953793-ZZZZ",
                status="posted")
    assert _card(db, 1).also_posted_by == []


def test_a_url_without_an_id_matches_only_itself(db, shared_post):
    plain = "https://www.linkedin.com/posts/p-1"
    shared_post(1, url=plain)
    shared_post(2, url=plain, status="posted")
    shared_post(3, url="https://www.linkedin.com/posts/p-10", status="posted")
    assert _card(db, 1).also_posted_by == ["Nikolina Lauc"]


def test_each_card_on_a_page_gets_its_own_label(db, shared_post):
    other = URL.replace("7520308138625953793", "7520308138625950000").replace("_sleep-", "_diet-")
    shared_post(1)
    shared_post(1, url=other)
    shared_post(2, status="posted")
    shared_post(3, url=other, status="approved")
    page = {p.post_url: p for p in P._paged_posts(db, 1, "all", 14, 60, 0)}
    assert page[URL].also_posted_by == ["Nikolina Lauc"] and page[URL].also_approved_for == []
    assert page[other].also_posted_by == [] and page[other].also_approved_for == ["Gordan Lauc"]


def test_archived_client_counts_for_posted_but_not_approved(db, shared_post):
    shared_post(1)
    shared_post(2, status="posted")
    shared_post(3, status="approved")
    for cid in (2, 3):
        db.get(Client, cid).archived = True
    db.commit()
    card = _card(db, 1)
    assert card.also_posted_by == ["Nikolina Lauc"]           # still under the post on LinkedIn
    assert card.also_approved_for == []                       # will never be posted


def test_feed_page_reaches_the_api_with_the_label(db, shared_post):
    from app.schemas import PostWithDrafts
    shared_post(1)
    shared_post(2, status="posted")
    shared_post(3, status="posted")
    out = PostWithDrafts.model_validate(_card(db, 1)).model_dump()
    assert out["also_posted_by"] == ["Gordan Lauc", "Nikolina Lauc"]
    assert out["also_approved_for"] == []


def test_labelling_does_not_write_to_the_database(db, shared_post):
    p = shared_post(1)
    shared_post(2, status="posted")
    _card(db, 1)
    db.commit()                                               # a dirty row would be flushed here
    assert db.get(Post, p.id).content_snippet == "x"


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
    shared_post(2, 0.1, url="https://www.linkedin.com/posts/p-2")
    r = report(db, db.get(Client, 2))
    assert r["posts_stored_in_window"] == 2
    assert r["where_they_went"] == {"in the feed": 1, "below the relevance bar": 1}
    assert r["profiles"]["assigned_creators"] == 1
    assert r["profiles"]["assigned_but_not_fetched"] == ["A Prospect (prospect)"]
