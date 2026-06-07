"""Tests for rating service."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rating import RatingService, _extract_json, _fallback_null_result


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
