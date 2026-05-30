"""Tests for tasks endpoints."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient):
    response = await client.get("/tasks/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_task(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    task = Task(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        topic_id=sample_topic.id,
        type="source_ingest",
        status="done",
        progress=100,
    )
    db_session.add(task)
    await db_session.commit()

    response = await client.get(f"/tasks/{task.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == task.id
    assert data["status"] == "done"
    assert data["progress"] == 100


@pytest.mark.asyncio
async def test_get_task_wrong_user(
    client: AsyncClient, db_session: AsyncSession
):
    """Task belonging to another user returns 404."""
    task = Task(
        id=str(uuid.uuid4()),
        user_id="other-user",
        type="source_ingest",
        status="pending",
        progress=0,
    )
    db_session.add(task)
    await db_session.commit()

    response = await client.get(f"/tasks/{task.id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_task_stream_done(
    client: AsyncClient, db_session: AsyncSession, sample_topic: Topic
):
    """Stream returns SSE with done event for completed task."""
    task = Task(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        topic_id=sample_topic.id,
        type="source_ingest",
        status="done",
        progress=100,
    )
    db_session.add(task)
    await db_session.commit()

    response = await client.get(f"/tasks/{task.id}/stream")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
    # The SSE stream should contain progress and done events
    content = response.text
    assert "event: progress" in content
    assert "event: done" in content
