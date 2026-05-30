"""Tests for chat endpoints."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.topic import Conversation, Topic
from app.routers.deps import TEST_USER_ID


@pytest.mark.asyncio
async def test_get_chat_history_empty(client: AsyncClient, sample_topic: Topic):
    response = await client.get(f"/topics/{sample_topic.id}/chat")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_chat_history(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    msg = Conversation(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        role="user",
        content="Hello",
    )
    db_session.add(msg)
    await db_session.commit()

    response = await client.get(f"/topics/{sample_topic.id}/chat")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "Hello"
    assert data[0]["role"] == "user"


@pytest.mark.asyncio
async def test_get_chat_topic_not_found(client: AsyncClient):
    response = await client.get("/topics/nonexistent/chat")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_post_chat_streams(client: AsyncClient, sample_topic: Topic, db_engine):
    """Test that POST /chat returns SSE stream."""
    import app.database as db_module
    from app.main import create_app
    from app.database import get_db
    from app.routers.deps import get_current_user, get_llm_adapter
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from httpx import ASGITransport, AsyncClient as HttpxClient

    # Mock LLM
    from unittest.mock import MagicMock

    mock_adapter = MagicMock()
    mock_adapter.model_name = "mock"

    async def mock_gen():
        yield "Hello"
        yield " world"

    async def mock_complete(messages, stream=False, max_tokens=4096):
        return mock_gen()

    mock_adapter.complete = mock_complete

    # Use the same db_engine from the fixture
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # Wire global state for SSE generator
    old_factory = db_module._async_session_factory
    old_engine = db_module._engine
    db_module._async_session_factory = factory
    db_module._engine = db_engine

    app = create_app()

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
    app.dependency_overrides[get_llm_adapter] = lambda: mock_adapter

    try:
        async with HttpxClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            # Create topic first
            create_resp = await c.post("/topics", json={"title": "Chat Test"})
            tid = create_resp.json()["id"]

            response = await c.post(
                f"/topics/{tid}/chat",
                json={"message": "Test message"},
            )
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            assert "event: done" in response.text
    finally:
        db_module._async_session_factory = old_factory
        db_module._engine = old_engine
