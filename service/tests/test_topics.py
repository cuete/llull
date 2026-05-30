"""Tests for topics CRUD endpoints."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_topic(client: AsyncClient):
    response = await client.post("/topics", json={"title": "My Research"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "My Research"
    assert "id" in data
    assert "user_id" in data
    assert data["context_summary"] is None


@pytest.mark.asyncio
async def test_list_topics_empty(client: AsyncClient):
    response = await client.get("/topics")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_topics(client: AsyncClient):
    await client.post("/topics", json={"title": "Topic A"})
    await client.post("/topics", json={"title": "Topic B"})
    response = await client.get("/topics")
    assert response.status_code == 200
    titles = [t["title"] for t in response.json()]
    assert "Topic A" in titles
    assert "Topic B" in titles


@pytest.mark.asyncio
async def test_get_topic(client: AsyncClient):
    create_resp = await client.post("/topics", json={"title": "Detail Test"})
    topic_id = create_resp.json()["id"]

    response = await client.get(f"/topics/{topic_id}")
    assert response.status_code == 200
    assert response.json()["id"] == topic_id


@pytest.mark.asyncio
async def test_get_topic_not_found(client: AsyncClient):
    response = await client.get("/topics/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_topic(client: AsyncClient):
    create_resp = await client.post("/topics", json={"title": "Original"})
    topic_id = create_resp.json()["id"]

    response = await client.patch(
        f"/topics/{topic_id}",
        json={"title": "Updated", "context_summary": "Some context"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated"
    assert data["context_summary"] == "Some context"


@pytest.mark.asyncio
async def test_delete_topic(client: AsyncClient):
    create_resp = await client.post("/topics", json={"title": "To Delete"})
    topic_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/topics/{topic_id}")
    assert del_resp.status_code == 204

    get_resp = await client.get(f"/topics/{topic_id}")
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_create_topic_empty_title(client: AsyncClient):
    response = await client.post("/topics", json={"title": ""})
    assert response.status_code == 422
