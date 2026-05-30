"""URL parser using httpx + BeautifulSoup."""
from __future__ import annotations

from pathlib import Path

import httpx
import structlog

from app.parsers.base import BaseParser

log = structlog.get_logger()

# Reasonable timeout for URL fetching
_FETCH_TIMEOUT = 30.0


class URLParser(BaseParser):
    """Fetch and extract text from a URL."""

    async def extract(self, source: Path | str) -> str:
        try:
            from bs4 import BeautifulSoup
        except ImportError as e:
            raise ImportError("beautifulsoup4 is required for URL parsing") from e

        url = str(source)
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
