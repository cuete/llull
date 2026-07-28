"""URL parser using httpx + BeautifulSoup."""
from __future__ import annotations

import re
from pathlib import Path

import httpx
import structlog

from app.parsers.base import BaseParser

log = structlog.get_logger()

# Reasonable timeout for URL fetching
_FETCH_TIMEOUT = 30.0

# Patterns that identify video/audio URLs not supported for text extraction
_UNSUPPORTED_URL_PATTERNS: list[re.Pattern] = [
    re.compile(r"youtube\.com/watch", re.IGNORECASE),
    re.compile(r"youtu\.be/", re.IGNORECASE),
    re.compile(r"youtube\.com/shorts", re.IGNORECASE),
    re.compile(r"vimeo\.com/", re.IGNORECASE),
    re.compile(r"tiktok\.com/", re.IGNORECASE),
    re.compile(r"twitter\.com/i/", re.IGNORECASE),
    re.compile(r"x\.com/i/", re.IGNORECASE),
    re.compile(r"spotify\.com/", re.IGNORECASE),
    re.compile(r"soundcloud\.com/", re.IGNORECASE),
    re.compile(r"\.(?:mp4|mp3|wav|ogg|webm|m4a|aac)(?:\?|$)", re.IGNORECASE),
]


def _check_unsupported_url(url: str) -> None:
    """Raise ValueError if the URL points to a video or audio source."""
    for pattern in _UNSUPPORTED_URL_PATTERNS:
        if pattern.search(url):
            raise ValueError(
                "Video and audio sources are not supported yet. "
                "Please provide a text transcript or article URL instead."
            )


class URLParser(BaseParser):
    """Fetch and extract text from a URL."""

    async def extract(self, source: Path | str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise ImportError("beautifulsoup4 is required for URL parsing") from e

        url = str(source)

        # Reject video/audio URLs before attempting any HTTP fetch
        _check_unsupported_url(url)

        log.info("url_extract_start", url=url)

        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            verify=True,  # Always validate TLS
        ) as client:
            try:
                response = await client.get(url, headers={"User-Agent": "Llull/0.1"})
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                log.error("url_fetch_failed", url=url, status=e.response.status_code)
                raise
            except httpx.RequestError as e:
                log.error("url_request_failed", url=url, error=str(e))
                raise

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove navigation, scripts, styles
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n", strip=True)
        log.info("url_extract_done", url=url, chars=len(text))
        return text
