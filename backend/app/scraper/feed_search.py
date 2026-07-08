"""Keyword/topic post search. LinkedIn has no first-party API for this — we drive
the actual search UI and parse rendered results. Expect this to need patching
whenever LinkedIn changes its search page markup."""
from urllib.parse import quote

from app.scraper.parsing import extract_posts_from_page
from app.scraper.rate_limit import human_delay

SEARCH_URL = "https://www.linkedin.com/search/results/content/?keywords={query}&sortBy=%22date_posted%22"


def search_posts_by_keyword(page, keyword: str, max_results: int = 10) -> list[dict]:
    url = SEARCH_URL.format(query=quote(keyword))
    page.goto(url, wait_until="domcontentloaded")
    human_delay()
    return extract_posts_from_page(page, max_results)
