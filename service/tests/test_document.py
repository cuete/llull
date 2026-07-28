"""Tests for document endpoints."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentBlock
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID


@pytest.mark.asyncio
async def test_get_document_creates_empty_on_missing(client: AsyncClient, sample_topic: Topic):
    # GET on a topic with no document should create and return an empty doc (not 404)
    response = await client.get(f"/topics/{sample_topic.id}/document")
    assert response.status_code == 200
    data = response.json()
    assert data["topic_id"] == sample_topic.id
    assert data["blocks"] == []


@pytest.mark.asyncio
async def test_get_document(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    doc = Document(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        route_summary="Summary",
    )
    db_session.add(doc)
    await db_session.flush()

    block = DocumentBlock(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        content_md="# Introduction\n\nSome content",
        order=0,
    )
    db_session.add(block)
    await db_session.commit()

    response = await client.get(f"/topics/{sample_topic.id}/document")
    assert response.status_code == 200
    data = response.json()
    assert data["topic_id"] == sample_topic.id
    assert data["route_summary"] == "Summary"
    assert len(data["blocks"]) == 1
    assert data["blocks"][0]["content_md"] == "# Introduction\n\nSome content"


@pytest.mark.asyncio
async def test_update_document_block(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    doc = Document(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
    )
    db_session.add(doc)
    await db_session.flush()

    block = DocumentBlock(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        content_md="Original content",
        order=0,
    )
    db_session.add(block)
    await db_session.commit()

    response = await client.patch(
        f"/topics/{sample_topic.id}/document/blocks/{block.id}",
        json={"content_md": "Updated content"},
    )
    assert response.status_code == 200
    assert response.json()["content_md"] == "Updated content"


@pytest.mark.asyncio
async def test_update_block_not_found(client: AsyncClient, sample_topic: Topic):
    response = await client.patch(
        f"/topics/{sample_topic.id}/document/blocks/nonexistent",
        json={"content_md": "Content"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_block_appends_to_document(
    client: AsyncClient, sample_topic: Topic
):
    # Creates a new block (document auto-created if missing)
    response = await client.post(
        f"/topics/{sample_topic.id}/document/blocks",
        json={"content_md": "# Chat Response\n\nSome analytical content.", "source": "chat"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["content_md"] == "# Chat Response\n\nSome analytical content."
    assert data["order"] == 0


@pytest.mark.asyncio
async def test_create_block_appends_after_existing(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    # Seed a document with one block, then add another via the API
    doc = Document(id=str(uuid.uuid4()), topic_id=sample_topic.id)
    db_session.add(doc)
    await db_session.flush()
    block0 = DocumentBlock(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        content_md="Existing block",
        order=0,
    )
    db_session.add(block0)
    await db_session.commit()

    response = await client.post(
        f"/topics/{sample_topic.id}/document/blocks",
        json={"content_md": "New block from chat", "source": "chat"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["content_md"] == "New block from chat"
    assert data["order"] == 1  # appended after existing block


@pytest.mark.asyncio
async def test_create_block_topic_not_found(client: AsyncClient):
    response = await client.post(
        "/topics/nonexistent-topic/document/blocks",
        json={"content_md": "Content"},
    )
    assert response.status_code == 404
