"""Tests for rating service."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rating import RatingService, _distributed_sample, _extract_json, _fallback_null_result


# ─── _distributed_sample unit tests ─────────────────────────────────────────────

def test_distributed_sample_short_text():
    """Text shorter than total_chars is returned as-is."""
    text = "short text here"
    assert _distributed_sample(text, total_chars=8000) == text


def test_distributed_sample_exact_chars():
    """Text of exactly total_chars is returned as-is."""
    text = "x" * 8000
    result = _distributed_sample(text, total_chars=8000)
    assert result == text


def test_distributed_sample_produces_five_parts():
    """Long text produces 5 samples joined by separators."""
    text = "A" * 100000
    result = _distributed_sample(text, total_chars=8000, n_samples=5)
    parts = result.split("\n\n---\n\n")
    assert len(parts) == 5


def test_distributed_sample_covers_start_and_end():
    """First sample starts near position 0; last sample starts near the end."""
    # Build a text where each character encodes its position region
    # Region 0: 'A' * 20000, Region 4: 'E' * 20000
    text = "A" * 20000 + "B" * 20000 + "C" * 20000 + "D" * 20000 + "E" * 20000
    result = _distributed_sample(text, total_chars=8000, n_samples=5)
    parts = result.split("\n\n---\n\n")
    assert parts[0][0] == "A"   # first sample from the start
    assert parts[-1][0] == "E"  # last sample from the end


def test_distributed_sample_total_chars_respected():
    """Total returned chars (excluding separators) ≤ total_chars."""
    text = "Z" * 100000
    result = _distributed_sample(text, total_chars=8000, n_samples=5)
    # Strip separators and count actual content characters
    content_chars = result.replace("\n\n---\n\n", "")
    assert len(content_chars) <= 8000


# ─── Unit tests for _extract_json ────────────────────────────────────────────

def test_extract_json_direct():
    obj = {"ai_suspicion": 40, "quality_score": 75}
    assert _extract_json(json.dumps(obj)) == obj


def test_extract_json_code_block():
    text = '```json\n{"ai_suspicion": 20, "quality_score": 80}\n```'
    result = _extract_json(text)
    assert result == {"ai_suspicion": 20, "quality_score": 80}


def test_extract_json_bare_code_block():
    text = '```\n{"ai_suspicion": 55}\n```'
    result = _extract_json(text)
    assert result == {"ai_suspicion": 55}


def test_extract_json_inline_object():
    text = 'Some text before {"ai_suspicion": 10} and after'
    result = _extract_json(text)
    assert result == {"ai_suspicion": 10}


def test_extract_json_invalid():
    assert _extract_json("not json at all") is None


# ─── RatingService tests ──────────────────────────────────────────────────────

def make_mock_llm(response_text: str) -> MagicMock:
    """Return a mock LLMAdapter that yields the given response text."""
    llm = MagicMock()

    async def mock_complete(messages, stream=False, max_tokens=4096):
        async def _gen():
            yield response_text
        return _gen()

    llm.complete = mock_complete
    return llm


@pytest.mark.asyncio
async def test_rate_source_short_text():
    """Text below MIN_WORDS threshold returns null scores."""
    llm = make_mock_llm("{}")
    svc = RatingService(llm)
    result = await svc.rate_source("too short")
    assert result["ai_suspicion"] is None
    assert result["quality_score"] is None
    assert "short" in result["ai_suspicion_reason"].lower()


@pytest.mark.asyncio
async def test_rate_source_success():
    """Valid LLM JSON response is parsed and scores clamped correctly."""
    payload = json.dumps({
        "ai_suspicion": 35,
        "ai_suspicion_reason": "Some AI markers detected.",
        "quality_score": 70,
        "quality_reason": "Good structure and cited sources.",
    })
    llm = make_mock_llm(payload)
    svc = RatingService(llm)

    long_text = "word " * 400  # 400 words, above MIN_WORDS
    result = await svc.rate_source(long_text)

    assert result["ai_suspicion"] == 35
    assert result["quality_score"] == 70
    assert "AI markers" in result["ai_suspicion_reason"]
    assert "cited sources" in result["quality_reason"]


@pytest.mark.asyncio
async def test_rate_source_clamps_over_100():
    """Scores above 100 are clamped to 100."""
    payload = json.dumps({
        "ai_suspicion": 150,
        "ai_suspicion_reason": "Too high",
        "quality_score": -5,
        "quality_reason": "Too low",
    })
    llm = make_mock_llm(payload)
    svc = RatingService(llm)
    result = await svc.rate_source("word " * 400)
    assert result["ai_suspicion"] == 100
    assert result["quality_score"] == 0


@pytest.mark.asyncio
async def test_rate_source_unparseable_response():
    """Unparseable LLM response returns null scores gracefully."""
    llm = make_mock_llm("I cannot analyze this document.")
    svc = RatingService(llm)
    result = await svc.rate_source("word " * 400)
    assert result["ai_suspicion"] is None
    assert result["quality_score"] is None


@pytest.mark.asyncio
async def test_rate_source_llm_exception():
    """LLM exception returns null scores gracefully."""
    llm = MagicMock()

    async def exploding_complete(messages, stream=False, max_tokens=4096):
        raise RuntimeError("LLM unreachable")

    llm.complete = exploding_complete
    svc = RatingService(llm)
    result = await svc.rate_source("word " * 400)
    assert result["ai_suspicion"] is None
    assert result["quality_score"] is None
