"""DOCX parser using python-docx."""
from __future__ import annotations

from pathlib import Path

import structlog

from app.parsers.base import BaseParser

log = structlog.get_logger()


class DocxParser(BaseParser):
    """Extract text from DOCX files."""

    async def extract(self, source: Path | str) -> str:
        try:
            from docx import Document
        except ImportError as e:
            raise ImportError("python-docx is required for DOCX parsing") from e

        path = Path(source) if isinstance(source, str) else source
        if not path.exists():
            raise FileNotFoundError(f"DOCX file not found: {path}")

        log.info("docx_extract_start", path=str(path))
        try:
            doc = Document(str(path))
            paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
            extracted = "\n\n".join(paragraphs)
        except Exception as e:
            log.error("docx_extract_failed", path=str(path), error=str(e))
            raise

        log.info("docx_extract_done", path=str(path), chars=len(extracted))
        return extracted
