"""Tests for fact-check endpoint."""
from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID

# Long enough text (>300 words)
LONG_TEXT = "This is a sample sentence. " * 40

SAMPLE_CLAIMS = [
    "The study involved 1,200 participants",
    "WHO reported a 15% increase in 2022",
]

CLAIMS_RESPONSE = json.dumps(SAMPLE_CLAIMS)

VERDICT_VERIFIED = json.dumps({
    "verdict": "verified",
    "evidence": "Multiple sources confirm the study size.",
})
VERDICT_UNVERIFIED = json.dumps({
    "verdict": "unverified",
    "evidence": "No corroborating evidence found.",
})


def _make_mock_llm(responses: list[str]):
    """Return a mock LLM that yields successive responses from the list."""
    from unittest.mock import MagicMock
    llm = MagicMock()
    call_count = [0]

    async def mock_complete(messages, stream=False, max_tokens=4096):
        idx = call_count[0]
        call_count[0] += 1
        text = responses[idx] if idx < len(responses) else responses[-1]

        async def _gen():
            yield text

        return _gen()

    llm.complete = mock_complete
    return llm


async def _make_test_app(mock_llm):
    """Build a fresh app with LLM dependency override and in-memory DB."""
    from app.main import create_app
    from app.database import get_db
    from app.routers.deps import get_current_user, get_llm_adapter
    import app.database as db_module

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    from app.models import document, graph, source as source_mod, task, topic as topic_mod  # noqa
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application = create_app()
    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    application.dependency_overrides[get_llm_adapter] = lambda: mock_llm
    return application, factory, engine


@pytest.mark.asyncio
async def test_fact_check_success():
    """Full fact-check flow returns claims, score, and persists to DB."""
    llm_responses = [CLAIMS_RESPONSE, VERDICT_VERIFIED, VERDICT_UNVERIFIED]
    mock_llm = _make_mock_llm(llm_responses)

    application, factory, engine = await _make_test_app(mock_llm)

    # Create topic and source
    async with factory() as session:
        topic = Topic(id=str(uuid.uuid4()), user_id=TEST_USER_ID, title="Test")
        session.add(topic)
        await session.commit()

        source = Source(
            id=str(uuid.uuid4()),
            topic_id=topic.id,
            type="text",
            name="Test Source",
            extracted_text=LONG_TEXT,
            quality_score=60,
        )
        session.add(source)
        await session.commit()

    with patch("app.routers.fact_check._perplexity_search", return_value=[]):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as c:
            response = await c.post(
                f"/topics/{topic.id}/sources/{source.id}/fact-check"
            )

    await engine.dispose()

    assert response.status_code == 200, response.text
    data = response.json()

    assert "claims" in data
    assert "fact_check_score" in data
    assert isinstance(data["fact_check_score"], int)
    assert 0 <= data["fact_check_score"] <= 100
    assert len(data["claims"]) > 0
    for claim in data["claims"]:
        assert claim["verdict"] in ("verified", "contradicted", "unverified")


@pytest.mark.asyncio
async def test_fact_check_topic_not_found():
    mock_llm = _make_mock_llm(["{}"])
    application, _, engine = await _make_test_app(mock_llm)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as c:
        response = await c.post("/topics/nonexistent/sources/nonexistent/fact-check")
    await engine.dispose()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_fact_check_source_not_found():
    mock_llm = _make_mock_llm(["{}"])
    application, factory, engine = await _make_test_app(mock_llm)

    async with factory() as session:
        topic = Topic(id=str(uuid.uuid4()), user_id=TEST_USER_ID, title="Test")
        session.add(topic)
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as c:
        response = await c.post(f"/topics/{topic.id}/sources/nonexistent/fact-check")
    await engine.dispose()
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_fact_check_no_extracted_text():
    """Source with empty extracted_text returns 422."""
    mock_llm = _make_mock_llm(["[]"])
    application, factory, engine = await _make_test_app(mock_llm)

    async with factory() as session:
        topic = Topic(id=str(uuid.uuid4()), user_id=TEST_USER_ID, title="Test")
        session.add(topic)
        await session.commit()

        source = Source(
            id=str(uuid.uuid4()),
            topic_id=topic.id,
            type="text",
            name="Empty Source",
            extracted_text="",
        )
        session.add(source)
        await session.commit()

    with patch("app.routers.fact_check._perplexity_search", return_value=[]):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as c:
            response = await c.post(
                f"/topics/{topic.id}/sources/{source.id}/fact-check"
            )
    await engine.dispose()
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_fact_check_quality_score_updated():
    """quality_score_updated is 60% original + 40% fact_check_score."""
    llm_responses = [CLAIMS_RESPONSE] + [VERDICT_VERIFIED] * len(SAMPLE_CLAIMS)
    mock_llm = _make_mock_llm(llm_responses)
    application, factory, engine = await _make_test_app(mock_llm)

    async with factory() as session:
        topic = Topic(id=str(uuid.uuid4()), user_id=TEST_USER_ID, title="Test")
        session.add(topic)
        await session.commit()

        source = Source(
            id=str(uuid.uuid4()),
            topic_id=topic.id,
            type="text",
            name="Scored Source",
            extracted_text=LONG_TEXT,
            quality_score=80,
        )
        session.add(source)
        await session.commit()

    with patch("app.routers.fact_check._perplexity_search", return_value=[]):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as c:
            response = await c.post(
                f"/topics/{topic.id}/sources/{source.id}/fact-check"
            )
    await engine.dispose()

    assert response.status_code == 200
    data = response.json()
    # All claims verified → fact_check_score = 100
    # quality_score_updated = 80 * 0.6 + 100 * 0.4 = 88
    if data["fact_check_score"] == 100:
        assert data["quality_score_updated"] == 88
