"""Image parser using pytesseract OCR."""
from __future__ import annotations

from pathlib import Path

import structlog

from app.parsers.base import BaseParser

log = structlog.get_logger()


class ImageParser(BaseParser):
    """Extract text from images using OCR (pytesseract)."""

    async def extract(self, source: Path | str) -> str:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            raise ImportError("pytesseract and Pillow are required for image parsing") from e

        path = Path(source) if isinstance(source, str) else source
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")

        log.info("image_extract_start", path=str(path))
        try:
            img = Image.open(str(path))
            extracted = pytesseract.image_to_string(img)
        except Exception as e:
            log.error("image_extract_failed", path=str(path), error=str(e))
            raise

        log.info("image_extract_done", path=str(path), chars=len(extracted))
        return extracted.strip()
