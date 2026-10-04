"""Split a source into sections (runs of consecutive chunks) and flag front/back matter."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Chunk, Section, Source

log = structlog.get_logger()

# Sections longer than this are split into parts so sampling stays fine-grained
MAX_SECTION_CHUNKS = 40
# Window size when the text has no detectable headings
FALLBACK_SECTION_CHUNKS = 12
# A heading is a short line; prose lines that merely start with "Chapter 7—..." are longer
MAX_HEADING_CHARS = 70
# Back-matter headings only end the content when they appear this far into the source
BACK_MATTER_START = 0.6

_ORDINALS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"primer[oa]?|segund[oa]|tercer[oa]?|cuart[oa]|quint[oa]|sext[oa]|s[eé]ptim[oa]|"
    r"octav[oa]|noven[oa]|d[eé]cim[oa]"
)
_NUMBERED_HEADING = re.compile(
    r"^(?:chapter|cap[ií]tulo|part|parte|section|secci[oó]n|art[ií]culo|article)"
    rf"\s+(?:\d+|[ivxlc]+|{_ORDINALS})\s*(?:[:.\-–—]\s*[^\W\d_].*)?$",
    re.IGNORECASE,
)
# A chunk with this many headings is a table of contents, not content
TOC_HEADINGS_PER_CHUNK = 3
_TOC_TITLE = "Contents"
_MARKDOWN_HEADING = re.compile(r"^#{1,3}\s+\S")
_FRONT_BACK_TITLES = (
    r"contents|table of contents|list of (?:figures|tables|boxes).*|acknowledge?ments|"
    r"notes|endnotes|bibliography|references|works cited|index|glossary|partial glossary|"
    r"[ií]ndice|contenido|agradecimientos|notas|bibliograf[ií]a|referencias|glosario"
)
_CONTENT_TITLES = (
    r"preface|foreword|introduction|conclusions?|epilogue|afterword|appendix.*|"
    r"prefacio|pr[oó]logo|introducci[oó]n|conclusi[oó]n|conclusiones|ep[ií]logo|ap[eé]ndice.*"
)
_NAMED_HEADING = re.compile(rf"^(?:{_FRONT_BACK_TITLES}|{_CONTENT_TITLES})\s*$", re.IGNORECASE)
_BOILERPLATE_TITLE = re.compile(rf"^(?:#+\s*)?(?:{_FRONT_BACK_TITLES})\s*$", re.IGNORECASE)
_BACK_MATTER_TITLE = re.compile(
    r"^(?:#+\s*)?(?:notes|endnotes|bibliography|references|works cited|index|"
    r"[ií]ndice|notas|bibliograf[ií]a|referencias)\s*$",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:1[89]|20)\d{2}\b")
_COPYRIGHT = re.compile(
    r"all rights reserved|todos los derechos reservados|\bISBN\b|library of congress cataloging",
    re.IGNORECASE,
)
_CITATION = re.compile(
    r"^\[?\d{1,3}\]\s|\b(?:cf|ib[ií]d|op\. ?cit|et al|pp?)\.\s|\bAAS\s+\d|\bvol\.\s*\d", re.IGNORECASE
)


@dataclass
class SectionSpan:
    """A section as a run of consecutive chunk positions [first, last]."""

    title: str
    first: int
    last: int
    is_boilerplate: bool = False


def _heading_title(lines: list[str], index: int) -> str | None:
    line = lines[index].strip()
    if not line or len(line) > MAX_HEADING_CHARS:
        return None
    if _MARKDOWN_HEADING.match(line):
        return line.lstrip("#").strip()
    if _NAMED_HEADING.match(line):
        return line
    if _NUMBERED_HEADING.match(line):
        title = line
        # A bare "CHAPTER 9" is followed by the chapter's name on the next line(s)
        if re.fullmatch(r"\S+\s+\S+", line):
            for extra in lines[index + 1 : index + 3]:
                extra = extra.strip()
                # Stop at drop caps, long lines, and prose (unless it is an all-caps title line)
                if len(extra) <= 2 or len(extra) > 60:
                    break
                if extra.endswith((".", ";")) and not extra.isupper():
                    break
                title += " " + extra
        return title
    return None


def is_low_information(text: str) -> bool:
    """True for index pages, reference lists and similar text that carries no ideas."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return True
    index_like = sum(1 for ln in lines if len(ln) < 45 and re.search(r"\d", ln))
    with_year = sum(1 for ln in lines if _YEAR.search(ln))
    citations = sum(1 for ln in lines if _CITATION.search(ln))
    digits = sum(ch.isdigit() for ch in text) / max(1, len(text))
    # Notes and references extracted from HTML/PDF come out as many very short lines
    fragmented = len(lines) > 15 and sum(len(ln) for ln in lines) / len(lines) < 25
    return (
        fragmented
        or bool(_COPYRIGHT.search(text))
        or index_like / len(lines) > 0.6
        or with_year / len(lines) > 0.45
        or citations / len(lines) > 0.4
        or digits > 0.2
    )


def detect_sections(chunk_texts: list[str]) -> list[SectionSpan]:
    """Group chunks into sections using headings; fixed windows when there are none."""
    if not chunk_texts:
        return []

    def _norm(title: str) -> str:
        return re.sub(r"\W+", " ", title).strip().lower()

    spans: list[SectionSpan] = []
    for position, text in enumerate(chunk_texts):
        lines = text.split("\n")
        titles = [t for t in (_heading_title(lines, i) for i in range(len(lines))) if t]
        if not titles:
            continue
        back_matter = [t for t in titles if _BACK_MATTER_TITLE.match(t)]
        if back_matter:
            # "NOTES" followed by a chapter-titled subsection: the notes heading wins
            title = back_matter[0]
        elif len(titles) >= TOC_HEADINGS_PER_CHUNK:
            title = _TOC_TITLE
        else:
            # With several headings in one chunk, the text that follows belongs to the last one
            title = titles[-1]
        # Overlapping chunks repeat a heading: the same title again is not a new section
        if spans and _norm(spans[-1].title) == _norm(title):
            continue
        spans.append(SectionSpan(title=title, first=position, last=position))

    total = len(chunk_texts)
    if not spans:
        spans = [
            SectionSpan(title="", first=start, last=min(start + FALLBACK_SECTION_CHUNKS, total) - 1)
            for start in range(0, total, FALLBACK_SECTION_CHUNKS)
        ]
    else:
        if spans[0].first > 0:
            spans.insert(0, SectionSpan(title="", first=0, last=spans[0].first - 1))
        for current, following in zip(spans, spans[1:]):
            current.last = following.first - 1
        spans[-1].last = total - 1

    # Flag front/back matter. A back-matter heading late in the source ends the content:
    # chapter-titled subsections of the notes must not come back as content.
    in_back_matter = False
    for span in spans:
        if _BACK_MATTER_TITLE.match(span.title) and span.first >= total * BACK_MATTER_START:
            in_back_matter = True
        chunk_range = chunk_texts[span.first : span.last + 1]
        low_information = sum(is_low_information(t) for t in chunk_range) / len(chunk_range)
        span.is_boilerplate = (
            in_back_matter or bool(_BOILERPLATE_TITLE.match(span.title)) or low_information > 0.6
        )

    # Split oversized content sections into parts
    result: list[SectionSpan] = []
    for span in spans:
        size = span.last - span.first + 1
        if span.is_boilerplate or size <= MAX_SECTION_CHUNKS:
            result.append(span)
            continue
        parts = -(-size // MAX_SECTION_CHUNKS)
        part_size = -(-size // parts)
        for part in range(parts):
            first = span.first + part * part_size
            result.append(
                SectionSpan(
                    title=f"{span.title} (part {part + 1} of {parts})" if span.title else "",
                    first=first,
                    last=min(first + part_size - 1, span.last),
                )
            )
    return result


async def ensure_sections(db: AsyncSession, source: Source) -> tuple[list[Section], list[Chunk]]:
    """Return the source's sections and chunks (in order), creating the sections if missing."""
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.source_id == source.id).order_by(Chunk.order)
    )
    chunks = list(chunks_result.scalars().all())

    sections_result = await db.execute(
        select(Section).where(Section.source_id == source.id).order_by(Section.order)
    )
    sections = list(sections_result.scalars().all())
    if sections or not chunks:
        return sections, chunks

    for order, span in enumerate(detect_sections([c.text for c in chunks])):
        section = Section(
            id=str(uuid.uuid4()),
            source_id=source.id,
            topic_id=source.topic_id,
            order=order,
            title=span.title or f"Section {order + 1}",
            is_boilerplate=span.is_boilerplate,
        )
        db.add(section)
        sections.append(section)
        for chunk in chunks[span.first : span.last + 1]:
            chunk.section_id = section.id
    await db.flush()
    log.info(
        "sections_created",
        source_id=source.id,
        sections=len(sections),
        boilerplate=sum(s.is_boilerplate for s in sections),
    )
    return sections, chunks
