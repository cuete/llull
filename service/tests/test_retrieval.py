"""Tests for chat source context selection when sources exceed the token budget."""
from __future__ import annotations

import pytest

from app.services.embeddings import EmbeddingService
from app.services.prompt import build_chat_context, count_tokens
from app.services.retrieval import ExcerptChunk, build_excerpt_context


class FakeEmbeddingService(EmbeddingService):
    """Embeds the question as a fixed vector; no model load."""

    def __init__(self, query_vector: list[float]) -> None:
        super().__init__()
        self._query_vector = query_vector

    async def embed_single(self, text: str) -> list[float]:
        return self._query_vector


def _chunks(count: int, relevant_index: int) -> list[ExcerptChunk]:
    return [
        ExcerptChunk(
            source_name="book.pdf",
            order=i,
            text=f"chunk-{i:04d} " + "lorem ipsum dolor sit amet " * 30,
            embedding=[1.0, 0.0] if i == relevant_index else [0.0, 1.0],
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_excerpts_cover_the_whole_document_and_the_relevant_chunk():
    chunks = _chunks(200, relevant_index=137)
    budget = 12_000  # far less than the ~41k tokens of chunks

    context = await build_excerpt_context(
        question="what about the relevant part?",
        chunks=chunks,
        concepts=[("Concept A", "First idea"), ("Concept B", "")],
        embedding_service=FakeEmbeddingService([1.0, 0.0]),
        token_budget=budget,
    )

    included = [i for i in range(200) if f"chunk-{i:04d} " in context]
    assert 137 in included  # most relevant to the question
    # Not just the start of the document: every quarter is represented
    for lo in (0, 50, 100, 150):
        assert any(lo <= i < lo + 50 for i in included)
    assert included == sorted(included)
    assert len(included) < 200

    assert "- Concept A: First idea" in context
    assert "- Concept B" in context
    assert "The sources themselves are complete" in context
    assert count_tokens(context) <= budget


@pytest.mark.asyncio
async def test_excerpt_context_is_not_truncated_by_build_chat_context():
    chunks = _chunks(200, relevant_index=10)
    budget = 12_000
    context = await build_excerpt_context(
        question="q",
        chunks=chunks,
        concepts=[],
        embedding_service=FakeEmbeddingService([1.0, 0.0]),
        token_budget=budget,
    )

    messages = build_chat_context(
        system_prompt="system",
        context_summary=None,
        conversation_history=[{"role": "user", "content": "q"}],
        source_texts=[context],
        max_tokens=budget + 500,
    )

    assert "...[truncated]" not in messages[1]["content"]


@pytest.mark.asyncio
async def test_excerpts_still_built_when_ranking_fails():
    class BrokenEmbeddingService(EmbeddingService):
        async def embed_single(self, text: str) -> list[float]:
            raise RuntimeError("model unavailable")

    context = await build_excerpt_context(
        question="q",
        chunks=_chunks(100, relevant_index=5),
        concepts=[],
        embedding_service=BrokenEmbeddingService(),
        token_budget=6_000,
    )

    assert "chunk-" in context
