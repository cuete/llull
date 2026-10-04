"""Source context selection for chat when the sources exceed the token budget."""
from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.services.embeddings import EmbeddingService

log = structlog.get_logger()

# Rough chars-per-token used for budgeting here; real text runs longer per token,
# so this errs on the side of staying under budget.
CHARS_PER_TOKEN = 4
# Share of the budget given to the concept-map overview
OVERVIEW_BUDGET_SHARE = 0.15
# Share of the excerpt budget spent on evenly spaced excerpts (coverage of the
# whole document); the rest goes to the excerpts most relevant to the question.
COVERAGE_SHARE = 0.35


@dataclass(frozen=True)
class ExcerptChunk:
    """A stored chunk of a source, in document order."""

    source_name: str
    order: int
    text: str
    embedding: list[float] | None


def _tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN + 1


def _build_overview(concepts: list[tuple[str, str]], token_budget: int) -> str:
    lines: list[str] = []
    used = 0
    for label, description in concepts:
        line = f"- {label}: {description}" if description else f"- {label}"
        cost = _tokens(line)
        if used + cost > token_budget:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


def _select_chunks(
    chunks: list[ExcerptChunk],
    scores: list[float],
    token_budget: int,
) -> list[int]:
    """Pick chunk indexes: evenly spaced ones for coverage, then the best-scoring ones."""
    costs = [_tokens(c.text) for c in chunks]
    selected: set[int] = set()
    used = 0

    avg_cost = max(1, sum(costs) // len(costs))
    coverage_count = max(1, int(token_budget * COVERAGE_SHARE) // avg_cost)
    step = max(1, len(chunks) // coverage_count)
    # Offset by half a step so the picks sit inside the document rather than on its front matter
    for i in range(step // 2, len(chunks), step):
        if used + costs[i] > token_budget * COVERAGE_SHARE:
            break
        selected.add(i)
        used += costs[i]

    for i in sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True):
        if i in selected:
            continue
        if used + costs[i] > token_budget:
            continue
        selected.add(i)
        used += costs[i]

    return sorted(selected)


async def build_excerpt_context(
    question: str,
    chunks: list[ExcerptChunk],
    concepts: list[tuple[str, str]],
    embedding_service: EmbeddingService,
    token_budget: int,
) -> str:
    """
    Build a source context that fits token_budget from sources that don't.

    Rather than keeping only the start of the text, this combines an overview of the
    concept map (built from the complete sources) with excerpts taken from across
    the whole document: evenly spaced ones plus those most relevant to the question.
    """
    overview = _build_overview(concepts, int(token_budget * OVERVIEW_BUDGET_SHARE))
    excerpt_budget = token_budget - _tokens(overview) - 300  # 300: headers and separators

    scores = [0.0] * len(chunks)
    if any(c.embedding for c in chunks):
        try:
            query = await embedding_service.embed_single(question)
            scores = [
                embedding_service.cosine_similarity(query, c.embedding) if c.embedding else 0.0
                for c in chunks
            ]
        except Exception as e:
            # Coverage excerpts still work without relevance ranking
            log.warning("excerpt_ranking_failed", error=str(e))

    picked = _select_chunks(chunks, scores, excerpt_budget) if chunks else []
    log.info("excerpt_context_built", chunks_total=len(chunks), chunks_included=len(picked))

    parts = [
        "The sources are too large to include in full. Below is (1) an overview of the "
        "concept map, which was built from the complete sources, and (2) "
        f"{len(picked)} of {len(chunks)} excerpts taken from across the whole of the sources, "
        "in their original order. The sources themselves are complete; passages not shown "
        "here were left out only to fit this context.",
    ]
    if overview:
        parts.append(f"### Concept map overview\n\n{overview}")

    excerpt_lines: list[str] = []
    previous: int | None = None
    for i in picked:
        chunk = chunks[i]
        contiguous = (
            previous is not None
            and i == previous + 1
            and chunks[previous].source_name == chunk.source_name
        )
        if not contiguous:
            excerpt_lines.append(f"\n[{chunk.source_name} — excerpt {i + 1} of {len(chunks)}]")
        excerpt_lines.append(chunk.text)
        previous = i
    if excerpt_lines:
        parts.append("### Excerpts\n" + "\n".join(excerpt_lines))

    return "\n\n".join(parts)
