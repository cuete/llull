"""Tests for analysis endpoints."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID


@pytest.fixture
async def topic_with_source(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
) -> tuple[Topic, Source]:
    source = Source(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        type="text",
        name="Test Source",
        extracted_text="The quick brown fox. Climate change affects biodiversity.",
    )
    db_session.add(source)
    await db_session.commit()
    return sample_topic, source


@pytest.mark.asyncio
async def test_analyze_no_sources(client: AsyncClient, sample_topic: Topic):
    """Analyze with no sources returns 400."""
    response = await client.post(f"/topics/{sample_topic.id}/analyze")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_analyze_topic_not_found(client: AsyncClient):
    response = await client.post("/topics/nonexistent/analyze")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analyze_l0_streams_and_builds_the_graph():
    """L0 analysis over HTTP streams SSE and stores a graph with the new fields."""
    from httpx import ASGITransport
    from httpx import AsyncClient as HttpxClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import Base, get_db
    from app.main import create_app
    from app.models import document, graph, task  # noqa: F401
    from app.models import source as source_mod  # noqa: F401
    from app.models import topic as topic_mod  # noqa: F401
    from app.routers.deps import get_current_user, get_embedding_service, get_llm_adapter
    from app.services.embeddings import EmbeddingService

    mock_llm = MagicMock()
    mock_llm.model_name = "mock"

    json_response = (
        '{"nodes": [{"label": "Fox", "description": "A quick fox", "sections": ["S1"]}], '
        '"edges": []}'
    )

    async def mock_complete(messages, stream=False, max_tokens=4096):
        async def mock_gen():
            yield json_response

        return mock_gen()

    mock_llm.complete = mock_complete

    class FakeEmbeddings(EmbeddingService):
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    app = create_app()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
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

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_llm_adapter] = lambda: mock_llm
    app.dependency_overrides[get_embedding_service] = lambda: FakeEmbeddings()

    async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        topic_resp = await c.post("/topics", json={"title": "Analysis Test"})
        tid = topic_resp.json()["id"]

        # Add source directly to DB (bypassing background task); it has no chunks yet
        async with factory() as direct_db:
            direct_db.add(
                Source(
                    id=str(uuid.uuid4()),
                    topic_id=tid,
                    type="text",
                    name="Doc",
                    extracted_text="Test content here about a quick fox.",
                )
            )
            await direct_db.commit()

        response = await c.post(f"/topics/{tid}/analyze")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert "event: done" in response.text

        graph_resp = (await c.get(f"/topics/{tid}/graph")).json()
        assert [n["label"] for n in graph_resp["nodes"]] == ["Fox"]
        node = graph_resp["nodes"][0]
        assert node["level"] == 0 and node["parent_id"] is None and node["coverage"] == 1.0

        # Already analyzed: refused unless forced
        assert (await c.post(f"/topics/{tid}/analyze")).status_code == 409
        forced = await c.post(f"/topics/{tid}/analyze?force=true")
        assert "event: done" in forced.text
        assert len((await c.get(f"/topics/{tid}/graph")).json()["nodes"]) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_zoom_node_not_found(client: AsyncClient, sample_topic: Topic):
    response = await client.post(f"/topics/{sample_topic.id}/zoom/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_keepalive_pings_while_the_stream_is_silent():
    import asyncio

    from app.routers.analysis import _with_keepalive

    async def slow_events():
        yield "event: progress\ndata: {}\n\n"
        await asyncio.sleep(0.12)  # a long LLM call
        yield "event: done\ndata: {}\n\n"

    received = [chunk async for chunk in _with_keepalive(slow_events(), interval=0.03)]

    assert received[0].startswith("event: progress")
    assert received[-1].startswith("event: done")
    assert received.count(": keepalive\n\n") >= 2
