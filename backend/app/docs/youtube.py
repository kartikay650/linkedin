"""YouTube transcript extraction — auto-captions only, no audio transcription fallback.
A video with no captions available is a real, expected outcome, not a bug."""
import re

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

_api = YouTubeTranscriptApi()


class TranscriptUnavailable(Exception):
    pass


def _video_id_from_url(url: str) -> str:
    patterns = [
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    raise TranscriptUnavailable(f"couldn't extract a video id from {url}")


def extract_youtube_transcript(url: str) -> str:
    video_id = _video_id_from_url(url)
    try:
        transcript = _api.fetch(video_id)
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable) as e:
        raise TranscriptUnavailable(f"no captions available for {url}: {e}") from e
    except Exception as e:
        # youtube_transcript_api's underlying scrape occasionally breaks in ways
        # it doesn't itself catch (YouTube response-format drift, transient
        # blocks) — any failure here should degrade to a clean "failed" document
        # status, never a 500.
        raise TranscriptUnavailable(f"couldn't fetch a transcript for {url}: {e}") from e
    return " ".join(snippet.text for snippet in transcript).strip()
