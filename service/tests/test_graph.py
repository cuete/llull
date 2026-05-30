"""Tests for graph endpoints."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import Edge, Node
from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID


async def _create_source(db: AsyncSession, topic_id: str) -> Source:
    source = Source(
        id=str(uuid.uuid4()),
        topic_id=topic_id,
        type="text",
        name="Test Source",
        extracted_text="content",
    )
    db.add(source)
    await db.flush()
    return source


async def _create_node(db: AsyncSession, topic_id: str, source_id: str, label: str) -> Node:
    node = Node(
        id=str(uuid.uuid4()),
        topic_id=topic_id,
        source_id=source_id,
        label=label,
        description=f"Description of {label}",
    )
    db.add(node)
    await db.flush()
    return node


@pytest.mark.asyncio
async def test_get_graph_empty(client: AsyncClient, sample_topic: Topic):
    response = await client.get(f"/topics/{sample_topic.id}/graph")
    assert response.status_code == 200
    data = response.json()
    assert data["nodes"] == []
    assert data["edges"] == []


@pytest.mark.asyncio
async def test_get_graph_with_nodes(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    source = await _create_source(db_session, sample_topic.id)
    node_a = await _create_node(db_session, sample_topic.id, source.id, "Concept A")
    node_b = await _create_node(db_session, sample_topic.id, source.id, "Concept B")

    edge = Edge(
        id=str(uuid.uuid4()),
        from_node_id=node_a.id,
        to_node_id=node_b.id,
        type="relational",
        weight=0.8,
        confidence=0.9,
    )
    db_session.add(edge)
    await db_session.commit()

    response = await client.get(f"/topics/{sample_topic.id}/graph")
    assert response.status_code == 200
    data = response.json()
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == 1
    labels = [n["label"] for n in data["nodes"]]
    assert "Concept A" in labels
    assert "Concept B" in labels


@pytest.mark.asyncio
async def test_get_graph_topic_not_found(client: AsyncClient):
    response = await client.get("/topics/nonexistent/graph")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_edge_weight(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    source = await _create_source(db_session, sample_topic.id)
    node_a = await _create_node(db_session, sample_topic.id, source.id, "A")
    node_b = await _create_node(db_session, sample_topic.id, source.id, "B")

    edge = Edge(
        id=str(uuid.uuid4()),
        from_node_id=node_a.id,
        to_node_id=node_b.id,
        type="causal",
        weight=0.5,
        confidence=0.7,
    )
    db_session.add(edge)
    await db_session.commit()

    response = await client.patch(
        f"/topics/{sample_topic.id}/edges/{edge.id}",
        json={"weight": 0.9},
    )
    assert response.status_code == 200
    assert response.json()["weight"] == pytest.approx(0.9)


@pytest.mark.asyncio
async def test_update_edge_weight_invalid(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    source = await _create_source(db_session, sample_topic.id)
    node_a = await _create_node(db_session, sample_topic.id, source.id, "A")
    node_b = await _create_node(db_session, sample_topic.id, source.id, "B")

    edge = Edge(
        id=str(uuid.uuid4()),
        from_node_id=node_a.id,
        to_node_id=node_b.id,
        type="relational",
        weight=0.5,
        confidence=0.7,
    )
    db_session.add(edge)
    await db_session.commit()

    # Weight > 1.0 should fail validation
    response = await client.patch(
        f"/topics/{sample_topic.id}/edges/{edge.id}",
        json={"weight": 1.5},
    )
    assert response.status_code == 422
