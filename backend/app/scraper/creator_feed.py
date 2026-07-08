"""Pull recent posts from a specific creator's profile activity feed."""
from app.scraper.parsing import extract_posts_from_page
from app.scraper.rate_limit import human_delay


def fetch_recent_posts(page, profile_url: str, max_results: int = 5) -> list[dict]:
    activity_url = profile_url.rstrip("/") + "/recent-activity/all/"
    page.goto(activity_url, wait_until="domcontentloaded")
    human_delay()

    results = extract_posts_from_page(page, max_results)
    for r in results:
        if not r["author_name"]:
            r["author_profile_url"] = profile_url
    return results
