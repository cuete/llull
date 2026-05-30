"""Parser registry."""
from __future__ import annotations

from app.parsers.base import BaseParser
from app.parsers.docx import DocxParser
from app.parsers.image import ImageParser
from app.parsers.pdf import PDFParser
from app.parsers.text import TextParser
from app.parsers.url import URLParser
from app.parsers.xlsx import XlsxParser

PARSER_REGISTRY: dict[str, type[BaseParser]] = {
    "pdf": PDFParser,
    "docx": DocxParser,
    "xlsx": XlsxParser,
    "text": TextParser,
    "url": URLParser,
    "image": ImageParser,
}


def get_parser(source_type: str) -> BaseParser:
    """Return the appropriate parser for the given source type."""
    cls = PARSER_REGISTRY.get(source_type)
    if cls is None:
        raise ValueError(f"No parser registered for source type: {source_type!r}")
    return cls()


__all__ = [
    "BaseParser",
    "PDFParser",
    "DocxParser",
    "XlsxParser",
    "TextParser",
    "URLParser",
    "ImageParser",
    "get_parser",
    "PARSER_REGISTRY",
]
