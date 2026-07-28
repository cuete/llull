"""Tests for the read-only mode enforcement middleware."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import get_cached_settings


@pytest.fixture
def read_only_enabled():
    """Flip the cached settings singleton to read-only for the duration of a test."""
    settings = get_cached_settings()
    original = settings.read_only
    settings.read_only = True
    yield
    settings.read_only = original


@pytest.mark.asyncio
async def test_health_reports_read_only(client: AsyncClient, read_only_enabled):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "read_only": True, "auth_enabled": False}


@pytest.mark.asyncio
async def test_post_blocked_when_read_only(client: AsyncClient, read_only_enabled):
    response = await client.post("/topics", json={"title": "Should not be created"})
    assert response.status_code == 403
    assert "read-only" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_patch_blocked_when_read_only(client: AsyncClient, sample_topic, read_only_enabled):
    response = await client.patch(f"/topics/{sample_topic.id}", json={"title": "Renamed"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_delete_blocked_when_read_only(client: AsyncClient, sample_topic, read_only_enabled):
    response = await client.delete(f"/topics/{sample_topic.id}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_still_allowed_when_read_only(client: AsyncClient, sample_topic, read_only_enabled):
    response = await client.get(f"/topics/{sample_topic.id}")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_writes_allowed_when_read_only_disabled(client: AsyncClient):
    response = await client.post("/topics", json={"title": "Fine to create"})
    assert response.status_code == 201
