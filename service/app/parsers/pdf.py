"""PDF parser using PyMuPDF (fitz)."""
from __future__ import annotations

from pathlib import Path

import structlog

from app.parsers.base import BaseParser

log = structlog.get_logger()


class PDFParser(BaseParser):
    """Extract text from PDF files using PyMuPDF."""

    async def extract(self, source: Path | str) -> str:
        try:
            import fitz  # pymupdf
        except ImportError as e:
            raise ImportError("pymupdf is required for PDF parsing") from e

        path = Path(source) if isinstance(source, str) else source
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")

        log.info("pdf_extract_start", path=str(path))
        texts: list[str] = []

        try:
            doc = fitz.open(str(path))
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                if text.strip():
                    texts.append(text)
            doc.close()
        except Exception as e:
            log.error("pdf_extract_failed", path=str(path), error=str(e))
            raise

        extracted = "\n\n".join(texts)
        log.info("pdf_extract_done", path=str(path), chars=len(extracted))
        return extracted
