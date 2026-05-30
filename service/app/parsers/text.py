"""Plain text parser."""
from __future__ import annotations

from pathlib import Path

from app.parsers.base import BaseParser


class TextParser(BaseParser):
    """Extract text from plain text files or raw text strings."""

    async def extract(self, source: Path | str) -> str:
        if isinstance(source, Path) or (isinstance(source, str) and Path(source).exists()):
            path = Path(source)
            return path.read_text(encoding="utf-8", errors="replace")
        # Raw text passed directly
        return str(source)
