"""Tests for export endpoint."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentBlock
from app.models.topic import Topic


@pytest.fixture
async def topic_with_document(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
) -> tuple[Topic, Document]:
    doc = Document(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        route_summary="Test summary",
    )
    db_session.add(doc)
    await db_session.flush()

    block = DocumentBlock(
        id=str(uuid.uuid4()),
        document_id=doc.id,
        content_md="# Test\n\nContent here.",
        order=0,
    )
    db_session.add(block)
    await db_session.commit()
    return sample_topic, doc


@pytest.mark.asyncio
async def test_export_md(
    client: AsyncClient, topic_with_document: tuple[Topic, Document]
):
    topic, doc = topic_with_document
    response = await client.get(f"/topics/{topic.id}/export?format=md")
    assert response.status_code == 200
    assert "text/markdown" in response.headers.get("content-type", "")
    assert "Content here" in response.text


@pytest.mark.asyncio
async def test_export_txt(
    client: AsyncClient, topic_with_document: tuple[Topic, Document]
):
    topic, doc = topic_with_document
    response = await client.get(f"/topics/{topic.id}/export?format=txt")
    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_export_zip(
    client: AsyncClient, topic_with_document: tuple[Topic, Document]
):
    topic, doc = topic_with_document
    response = await client.get(f"/topics/{topic.id}/export?format=zip")
    assert response.status_code == 200
    assert "application/zip" in response.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_export_invalid_format(
    client: AsyncClient, sample_topic: Topic
):
    response = await client.get(f"/topics/{sample_topic.id}/export?format=docx")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_export_no_document(client: AsyncClient, sample_topic: Topic):
    response = await client.get(f"/topics/{sample_topic.id}/export?format=md")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_topic_not_found(client: AsyncClient):
    response = await client.get("/topics/nonexistent/export?format=md")
    assert response.status_code == 404
