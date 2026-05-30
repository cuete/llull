"""Base parser interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class BaseParser(ABC):
    """Base class for all source parsers."""

    @abstractmethod
    async def extract(self, source: Path | str) -> str:
        """
        Extract text from the source.

        Args:
            source: File path (Path) or URL/text string.

        Returns:
            Extracted text content.
        """
        ...
