"""Tests for analysis endpoints and service utilities."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID
from app.services.analysis import merge_graphs, split_into_sections


# ─── split_into_sections unit tests ──────────────────────────────────────────

def test_split_markdown_headers():
    """Splits on markdown headers."""
    text = (
        "# Introduction\nThis is the intro.\n\n"
        "## Background\nSome background text.\n\n"
        "### Details\nDetailed information here."
    )
    sections = split_into_sections(text)
    assert len(sections) == 3
    assert "Introduction" in sections[0]
    assert "Background" in sections[1]
    assert "Details" in sections[2]


def test_split_capitulo_pattern():
    """Splits on Capítulo N pattern."""
    text = (
        "Capítulo I\nPrimera parte del texto.\n\n"
        "Capítulo II\nSegunda parte del texto.\n\n"
        "Capítulo III\nTercera parte."
    )
    sections = split_into_sections(text)
    assert len(sections) == 3
    assert "Primera" in sections[0]
    assert "Segunda" in sections[1]
    assert "Tercera" in sections[2]


def test_split_no_boundaries():
    """Returns [whole_text] when no boundaries found."""
    text = "This is plain text with no headers or chapter markers."
    sections = split_into_sections(text)
    assert len(sections) == 1
    assert sections[0] == text


def test_split_oversized_section():
    """Section > max_section_chars is sub-split at paragraph boundaries."""
    # Build a text with one implicit section that exceeds 500 chars
    para = "A" * 200
    text = f"{para}\n\n{para}\n\n{para}\n\n{para}"
    sections = split_into_sections(text, max_section_chars=500)
    # Total chars = 800 + separators; must produce >1 section
    assert len(sections) > 1
    for s in sections:
        assert len(s) <= 500


def test_split_returns_nonempty():
    """No empty sections returned."""
    text = "# H1\n\n# H2\n\n# H3\nContent here."
    sections = split_into_sections(text)
    assert all(s.strip() for s in sections)


# ─── merge_graphs unit tests ─────────────────────────────────────────────────

def test_merge_deduplicates_nodes():
    """Duplicate node labels produce one node in output."""
    g1 = {
        "nodes": [{"label": "Climate Change", "description": "Global warming."}],
        "edges": [],
    }
    g2 = {
        "nodes": [
            {"label": "Climate Change", "description": "Synonym."},
            {"label": "Biodiversity", "description": "Species variety."},
        ],
        "edges": [],
    }
    merged = merge_graphs([g1, g2])
    labels = [n["label"] for n in merged["nodes"]]
    assert labels.count("Climate Change") == 1
    assert "Biodiversity" in labels


def test_merge_averages_duplicate_edges():
    """Duplicate (from, to, type) edges are averaged."""
    g1 = {
        "nodes": [
            {"label": "A", "description": "Node A"},
            {"label": "B", "description": "Node B"},
        ],
        "edges": [{"from_label": "A", "to_label": "B", "type": "causal", "weight": 0.8, "confidence": 0.9}],
    }
    g2 = {
        "nodes": [
            {"label": "A", "description": "Node A"},
            {"label": "B", "description": "Node B"},
        ],
        "edges": [{"from_label": "A", "to_label": "B", "type": "causal", "weight": 0.4, "confidence": 0.6}],
    }
    merged = merge_graphs([g1, g2])
    assert len(merged["edges"]) == 1
    edge = merged["edges"][0]
    assert abs(edge["weight"] - 0.6) < 0.001
    assert abs(edge["confidence"] - 0.75) < 0.001


def test_merge_empty_graphs():
    """Merging empty graphs returns empty nodes and edges."""
    merged = merge_graphs([{"nodes": [], "edges": []}, {"nodes": [], "edges": []}])
    assert merged["nodes"] == []
    assert merged["edges"] == []


def test_merge_no_self_loops():
    """Edges where from == to are not created."""
    g = {
        "nodes": [{"label": "X", "description": "desc"}],
        "edges": [{"from_label": "X", "to_label": "X", "type": "relational", "weight": 0.5, "confidence": 0.5}],
    }
    merged = merge_graphs([g])
    assert merged["edges"] == []


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
async def test_analyze_l0_streams(
    client: AsyncClient,
    db_session: AsyncSession,
    topic_with_source: tuple[Topic, Source],
):
    """L0 analysis returns SSE stream."""
    from app.main import create_app
    from app.database import get_db
    from app.routers.deps import get_current_user, get_llm_adapter
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.database import Base
    from app.models import document, graph, source as source_mod, task, topic as topic_mod  # noqa
    from httpx import ASGITransport, AsyncClient as HttpxClient

    # Mock LLM
    mock_llm = MagicMock()
    mock_llm.model_name = "mock"

    json_response = '{"nodes": [{"label": "Fox", "description": "A quick fox"}], "edges": []}'

    async def mock_gen():
        yield json_response

    async def mock_complete(messages, stream=False, max_tokens=4096):
        return mock_gen()

    mock_llm.complete = mock_complete

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

    async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Create topic
        topic_resp = await c.post("/topics", json={"title": "Analysis Test"})
        tid = topic_resp.json()["id"]

        # Add source directly to DB (bypassing background task)
        async with factory() as direct_db:
            from app.models.source import Source as SourceModel
            src = SourceModel(
                id=str(uuid.uuid4()),
                topic_id=tid,
                type="text",
                name="Doc",
                extracted_text="Test content here.",
            )
            direct_db.add(src)
            await direct_db.commit()

        response = await c.post(f"/topics/{tid}/analyze")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

    await engine.dispose()


@pytest.mark.asyncio
async def test_zoom_node_not_found(client: AsyncClient, sample_topic: Topic):
    response = await client.post(f"/topics/{sample_topic.id}/zoom/nonexistent")
    assert response.status_code == 404
