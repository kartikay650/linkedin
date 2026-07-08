"""Shared post-extraction logic. Instead of keying off a specific CSS module
class (which LinkedIn changes often — see feed-shared-update-v2 breaking
across multiple scraper repos), this keys off actual post permalink URLs,
which are a much more stable signal, then walks up the DOM to find the
nearest ancestor with real text content."""

POST_LINK_SELECTOR = "a[href*='/feed/update/urn:li:activity'], a[href*='/posts/']"

_EXTRACT_JS = """
() => {
    const anchors = Array.from(document.querySelectorAll("POST_LINK_SELECTOR_PLACEHOLDER"));
    const seen = new Set();
    const results = [];
    for (const a of anchors) {
        const href = a.getAttribute('href');
        if (!href || seen.has(href)) continue;
        seen.add(href);

        let node = a;
        let text = '';
        for (let i = 0; i < 8 && node; i++) {
            if (node.innerText && node.innerText.trim().length > 60) {
                text = node.innerText.trim();
                break;
            }
            node = node.parentElement;
        }
        const scope = node || a;
        const authorAnchor = scope.querySelector("a[href*='/in/']");

        results.push({
            href,
            text: text.slice(0, 600),
            authorHref: authorAnchor ? authorAnchor.getAttribute('href') : null,
            authorName: authorAnchor ? authorAnchor.innerText.trim() : '',
        });
    }
    return results;
}
""".replace("POST_LINK_SELECTOR_PLACEHOLDER", POST_LINK_SELECTOR)


def extract_posts_from_page(page, max_results: int) -> list[dict]:
    page.wait_for_selector(POST_LINK_SELECTOR, timeout=15000)
    raw = page.evaluate(_EXTRACT_JS)

    results = []
    for item in raw[:max_results]:
        href = item["href"]
        post_url = href if href.startswith("http") else f"https://www.linkedin.com{href}"
        author_href = item.get("authorHref")
        author_url = (
            author_href if not author_href or author_href.startswith("http")
            else f"https://www.linkedin.com{author_href}"
        )
        results.append({
            "author_name": item.get("authorName", ""),
            "author_profile_url": author_url or "",
            "post_url": post_url,
            "content_snippet": item.get("text", ""),
            "posted_at": None,
            "engagement": {},
        })
    return results
