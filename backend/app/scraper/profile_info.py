"""Pull a quick name/headline/about preview from a person's own LinkedIn profile
page (not /recent-activity/, which has proven to be a much stronger checkpoint
trigger — see session notes). Used to prefill the "add client" form; the human
always reviews/edits the result before it's saved, so partial/empty extraction
is an acceptable degraded result, not a failure worth raising on its own."""

_EXTRACT_JS = """
() => {
    const text = (el) => (el && el.innerText ? el.innerText.trim() : '');

    const name = text(document.querySelector('h1'));

    const headlineCandidates = [
        '.text-body-medium.break-words',
        '[data-generated-suggestion-target]',
        'h1 + div',
    ];
    let headline = '';
    for (const sel of headlineCandidates) {
        const el = document.querySelector(sel);
        if (el && text(el) && text(el) !== name) { headline = text(el); break; }
    }

    let about = '';
    const aboutSection = Array.from(document.querySelectorAll('section')).find(
        (s) => s.innerText && s.innerText.trim().startsWith('About')
    );
    if (aboutSection) {
        const visible = aboutSection.querySelector('span[aria-hidden="true"]');
        about = text(visible) || aboutSection.innerText.replace(/^About\\s*/, '').trim();
    }

    return { name, headline, about: about.slice(0, 2000) };
}
"""


def fetch_profile_summary(page, profile_url: str) -> dict:
    page.goto(profile_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    data = page.evaluate(_EXTRACT_JS)
    return {
        "name": data.get("name", "") or "",
        "headline": data.get("headline", "") or "",
        "about": data.get("about", "") or "",
    }
