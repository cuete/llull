"""Export service — convert document to various formats."""
from __future__ import annotations

import asyncio
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from app.models.document import Document

log = structlog.get_logger()

PANDOC_TIMEOUT = 30  # seconds


class ExportService:
    """Export documents to PDF, Markdown, HTML, TXT, or ZIP."""

    async def export(self, document: "Document", fmt: str) -> tuple[bytes, str]:
        """
        Export document to the requested format.

        Returns (content_bytes, mime_type).
        """
        markdown = self._document_to_markdown(document)

        match fmt.lower():
            case "md":
                return markdown.encode("utf-8"), "text/markdown"
            case "txt":
                return self._strip_markdown(markdown).encode("utf-8"), "text/plain"
            case "html":
                html = await self._pandoc_convert(markdown, "html")
                return html.encode("utf-8"), "text/html"
            case "pdf":
                pdf_bytes = await self._pandoc_convert_bytes(markdown, "pdf")
                return pdf_bytes, "application/pdf"
            case "zip":
                return await self._export_zip(document, markdown), "application/zip"
            case _:
                raise ValueError(f"Unsupported export format: {fmt!r}")

    def _document_to_markdown(self, document: "Document") -> str:
        """Convert document blocks to Markdown."""
        lines: list[str] = [f"# Document\n"]
        if document.route_summary:
            lines.append(f"_{document.route_summary}_\n")
        lines.append("---\n")

        for block in sorted(document.blocks, key=lambda b: b.order):
            lines.append(block.content_md)
            lines.append("")

        return "\n".join(lines)

    def _strip_markdown(self, text: str) -> str:
        """Very basic markdown stripping for plain text output."""
        import re

        text = re.sub(r"#+\s*", "", text)
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"`(.*?)`", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        return text

    async def _pandoc_convert(self, markdown: str, output_fmt: str) -> str:
        """Convert markdown to target format using pandoc."""
        result = await self._run_pandoc(markdown, output_fmt)
        return result.decode("utf-8")

    async def _pandoc_convert_bytes(self, markdown: str, output_fmt: str) -> bytes:
        """Convert markdown to binary format using pandoc."""
        return await self._run_pandoc(markdown, output_fmt)

    async def _run_pandoc(self, markdown: str, output_fmt: str) -> bytes:
        """Run pandoc with timeout. Falls back to markdown on failure."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pandoc",
                "-f",
                "markdown",
                "-t",
                output_fmt,
                "--standalone",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=markdown.encode("utf-8")),
                timeout=PANDOC_TIMEOUT,
            )
            if proc.returncode != 0:
                log.error("pandoc_failed", fmt=output_fmt, stderr=stderr.decode())
                return markdown.encode("utf-8")
            return stdout
        except (FileNotFoundError, asyncio.TimeoutError) as e:
            log.warning("pandoc_unavailable", fmt=output_fmt, error=str(e))
            return markdown.encode("utf-8")

    async def _export_zip(self, document: "Document", markdown: str) -> bytes:
        """Create a ZIP archive with markdown + source references."""
        import io

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("document.md", markdown)
            # Include individual block files
            for block in document.blocks:
                filename = f"blocks/block_{block.order:03d}.md"
                zf.writestr(filename, block.content_md)
        buf.seek(0)
        return buf.read()
