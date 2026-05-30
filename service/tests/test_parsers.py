"""Tests for source parsers."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.parsers import get_parser
from app.parsers.text import TextParser
from app.parsers.url import URLParser


@pytest.mark.asyncio
async def test_text_parser_from_string():
    parser = TextParser()
    result = await parser.extract("Hello, world!")
    assert result == "Hello, world!"


@pytest.mark.asyncio
async def test_text_parser_from_file(tmp_path: Path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("Line 1\nLine 2\nLine 3", encoding="utf-8")

    parser = TextParser()
    result = await parser.extract(test_file)
    assert "Line 1" in result
    assert "Line 2" in result


@pytest.mark.asyncio
async def test_get_parser_text():
    parser = get_parser("text")
    assert isinstance(parser, TextParser)


@pytest.mark.asyncio
async def test_get_parser_url():
    parser = get_parser("url")
    assert isinstance(parser, URLParser)


@pytest.mark.asyncio
async def test_get_parser_unknown():
    with pytest.raises(ValueError, match="No parser registered"):
        get_parser("unknown_type")


@pytest.mark.asyncio
async def test_pdf_parser_file_not_found(tmp_path: Path):
    from app.parsers.pdf import PDFParser

    parser = PDFParser()
    with pytest.raises(FileNotFoundError):
        await parser.extract(tmp_path / "nonexistent.pdf")


@pytest.mark.asyncio
async def test_docx_parser_file_not_found(tmp_path: Path):
    from app.parsers.docx import DocxParser

    parser = DocxParser()
    with pytest.raises(FileNotFoundError):
        await parser.extract(tmp_path / "nonexistent.docx")


@pytest.mark.asyncio
async def test_xlsx_parser_file_not_found(tmp_path: Path):
    from app.parsers.xlsx import XlsxParser

    parser = XlsxParser()
    with pytest.raises(FileNotFoundError):
        await parser.extract(tmp_path / "nonexistent.xlsx")


@pytest.mark.asyncio
async def test_image_parser_file_not_found(tmp_path: Path):
    from app.parsers.image import ImageParser

    parser = ImageParser()
    with pytest.raises(FileNotFoundError):
        await parser.extract(tmp_path / "nonexistent.png")


@pytest.mark.asyncio
async def test_url_parser_fetches_and_extracts(respx_mock):
    """URL parser fetches HTML and extracts text."""
    import respx
    import httpx

    respx_mock.get("https://example.com").mock(
        return_value=httpx.Response(
            200,
            text="<html><body><p>Hello from the web!</p></body></html>",
            headers={"content-type": "text/html"},
        )
    )

    parser = URLParser()
    result = await parser.extract("https://example.com")
    assert "Hello from the web" in result
