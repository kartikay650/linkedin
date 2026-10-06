"""Which language is a post written in?

Several tracked creators post in German, French, Dutch, Spanish or Italian. Those posts reach the
engagement queue and the tool drafts comments in that language, which no client wants to post.

Detection is deterministic stopword counting rather than an LLM call or a library:
  - it runs over the ~5,000 posts already stored, for free, which an LLM pass would not;
  - it still works when the relevance call fails, and that call already fails open;
  - it adds no dependency to a serverless bundle and no latency to the scrape path.

The bias is deliberately conservative. A false positive hides a genuine English post from the
queue, which is worse than letting the occasional German one through, so a post is only called
non-English when another language clearly out-scores English.
"""
import re

# Function words. These are the highest-signal tokens for telling European languages apart: they
# are frequent, short, and rarely shared across languages. Words that collide with English
# ("die", "man", "sie", "we", "son", "come", "no", "a", "e") are left out on purpose.
_STOPWORDS = {
    "en": {"the", "and", "that", "with", "this", "from", "have", "which", "they", "about",
           "would", "there", "their", "what", "when", "been", "were", "than", "into", "also",
           "because", "could", "should", "these", "those", "after", "before", "where", "while"},
    "de": {"und", "nicht", "werden", "wird", "auch", "aber", "noch", "schon", "sich", "ich",
           "eine", "einen", "einem", "einer", "ist", "sind", "war", "haben", "hat", "wenn",
           "dass", "mehr", "sehr", "durch", "über", "unter", "zwischen", "immer", "bei", "dem",
           "den", "des", "für", "mit", "von", "zum", "zur", "oder", "wie", "was", "kann"},
    "fr": {"les", "des", "une", "nous", "vous", "pour", "avec", "dans", "cette", "mais",
           "plus", "tout", "tous", "être", "sont", "était", "leur", "nos", "aux", "ces",
           "qui", "quoi", "donc", "ainsi", "chez", "entre", "depuis", "pendant", "toujours",
           "jamais", "beaucoup", "aussi", "très", "elle", "ils", "elles", "faire", "fait"},
    "nl": {"het", "een", "niet", "maar", "ook", "zijn", "voor", "wordt", "worden", "deze",
           "daar", "hier", "waar", "door", "over", "onder", "tussen", "altijd", "nooit",
           "veel", "meer", "heel", "zeer", "naar", "bij", "van", "aan", "dat", "zoals",
           "omdat", "want", "dus", "nog", "wel", "heeft", "hebben", "kunnen", "moet"},
    "es": {"que", "los", "las", "una", "por", "con", "para", "más", "pero", "como", "este",
           "esta", "estos", "son", "está", "están", "desde", "hasta", "entre", "sobre",
           "también", "muy", "todo", "todos", "porque", "cuando", "donde", "hacer", "puede",
           "tiene", "sus", "del", "les", "nos", "sin", "ya", "así"},
    "it": {"che", "non", "per", "con", "una", "degli", "della", "dello", "sono", "questo",
           "questa", "anche", "come", "più", "molto", "tutto", "tutti", "quando", "dove",
           "perché", "però", "quindi", "essere", "fare", "nel", "nella", "dal", "dalla",
           "sul", "sulla", "loro", "suo", "sua", "gli", "alle", "agli"},
}

# Characters that essentially never appear in English prose. Used only as a tie-breaker, since a
# single "café" or "Müller" in an English post must not flip it.
_DIACRITIC_HINTS = {
    "de": "äöüß", "fr": "àâçéèêëîïôûùüÿœ", "nl": "ëïéèü",
    "es": "áéíóúñ¿¡", "it": "àèéìòù",
}

_WORD_RE = re.compile(r"[a-zà-öø-ÿß]+", re.I)

# Below this, there are too few function words for a count to mean anything. Short posts stay
# English by default rather than being guessed at.
_MIN_WORDS = 25
# The leading language must beat English by this margin, as a share of words, before a post is
# called non-English. Tuned against the real corpus — see tests in the commit.
_MARGIN = 0.02


def detect_language(text: str) -> str:
    """Return a two-letter code, or "en" when English or undecidable.

    Deliberately returns "en" rather than "unknown" for anything it cannot call, so a caller can
    treat the result as "safe to show" without a second branch.
    """
    words = [w.lower() for w in _WORD_RE.findall(text or "")]
    if len(words) < _MIN_WORDS:
        return "en"
    total = len(words)
    scores = {
        lang: sum(1 for w in words if w in stop) / total
        for lang, stop in _STOPWORDS.items()
    }
    # Diacritics nudge, never decide: at most one stopword's worth of score.
    low = (text or "").lower()
    for lang, chars in _DIACRITIC_HINTS.items():
        if any(c in low for c in chars):
            scores[lang] += min(sum(low.count(c) for c in chars), 3) / total

    english = scores.pop("en")
    best_lang, best = max(scores.items(), key=lambda kv: kv[1])
    if best > english + _MARGIN:
        return best_lang
    return "en"


def is_english(text: str) -> bool:
    return detect_language(text) == "en"
