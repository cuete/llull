"""Pytest configuration and shared fixtures."""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import AsyncGenerator as AG
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, init_db
from app.main import create_app
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID

# Use in-memory SQLite for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a fresh in-memory database engine per test."""
    engine = create_async_engine(TEST_DB_URL, echo=False)

    # Import all models before creating tables
    from app.models import document, graph, source, task, topic  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session."""
    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async test client with overridden DB."""
    import app.database as db_module
    from app.database import get_db
    from app.routers.deps import get_current_user

    factory = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    # Inject the test factory into the global module state so SSE generators
    # that call get_session_factory() directly can also use the test DB.
    old_engine = db_module._engine
    old_factory = db_module._async_session_factory
    db_module._engine = db_engine
    db_module._async_session_factory = factory

    async def override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def override_get_user():
        return TEST_USER_ID

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    # Restore global state
    db_module._engine = old_engine
    db_module._async_session_factory = old_factory


@pytest_asyncio.fixture
async def sample_topic(db_session: AsyncSession) -> Topic:
    """Create a sample topic for testing."""
    topic = Topic(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        title="Test Topic",
    )
    db_session.add(topic)
    await db_session.commit()
    await db_session.refresh(topic)
    return topic


@pytest.fixture
def mock_llm() -> MagicMock:
    """Mock LLM adapter that returns canned responses."""
    from app.services.llm.base import LLMAdapter

    adapter = MagicMock(spec=LLMAdapter)
    adapter.model_name = "mock-model"

    async def mock_complete(messages, stream=False, max_tokens=4096):
        response_text = '{"nodes": [{"label": "Test Node", "description": "A test concept"}], "edges": []}'

        async def _gen():
            yield response_text

        return _gen()

    async def mock_embed(texts):
        return [[0.1] * 768 for _ in texts]

    adapter.complete = mock_complete
    adapter.embed = mock_embed
    return adapter


@pytest.fixture
def mock_embedding_service() -> MagicMock:
    """Mock embedding service."""
    from app.services.embeddings import EmbeddingService

    svc = MagicMock(spec=EmbeddingService)

    async def mock_embed(texts):
        return [[0.1] * 768 for _ in texts]

    async def mock_embed_single(text):
        return [0.1] * 768

    svc.embed = mock_embed
    svc.embed_single = mock_embed_single
    svc.serialize = lambda x: str(x)
    svc.deserialize = lambda x: [0.1] * 768
    return svc
