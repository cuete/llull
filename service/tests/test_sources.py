"""Tests for sources endpoints."""
from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import TEST_USER_ID


@pytest.mark.asyncio
async def test_list_sources_empty(client: AsyncClient, sample_topic: Topic):
    response = await client.get(f"/topics/{sample_topic.id}/sources")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_sources_topic_not_found(client: AsyncClient):
    response = await client.get("/topics/nonexistent/sources")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_upload_text_source_creates_task(
    client: AsyncClient, sample_topic: Topic
):
    """POST /topics/{id}/sources with text content returns 202 with task_id."""
    response = await client.post(
        f"/topics/{sample_topic.id}/sources",
        data={
            "source_type": "text",
            "name": "My Text",
            "content": "Hello world, this is a test document.",
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert "task_id" in data
    assert isinstance(data["task_id"], str)


@pytest.mark.asyncio
async def test_upload_url_source_creates_task(
    client: AsyncClient, sample_topic: Topic
):
    response = await client.post(
        f"/topics/{sample_topic.id}/sources",
        data={
            "source_type": "url",
            "name": "Example",
            "content": "https://example.com",
        },
    )
    assert response.status_code == 202
    assert "task_id" in response.json()


@pytest.mark.asyncio
async def test_patch_source(client: AsyncClient, db_session: AsyncSession, sample_topic: Topic):
    """PATCH a source name."""
    source = Source(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        type="text",
        name="Old Name",
        extracted_text="content",
    )
    db_session.add(source)
    await db_session.commit()

    response = await client.patch(
        f"/topics/{sample_topic.id}/sources/{source.id}",
        json={"name": "New Name"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_source(client: AsyncClient, db_session: AsyncSession, sample_topic: Topic):
    source = Source(
        id=str(uuid.uuid4()),
        topic_id=sample_topic.id,
        type="text",
        name="To Delete",
        extracted_text="content",
    )
    db_session.add(source)
    await db_session.commit()

    del_resp = await client.delete(f"/topics/{sample_topic.id}/sources/{source.id}")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/topics/{sample_topic.id}/sources")
    source_ids = [s["id"] for s in list_resp.json()]
    assert source.id not in source_ids


@pytest.mark.asyncio
async def test_delete_source_not_found(client: AsyncClient, sample_topic: Topic):
    response = await client.delete(f"/topics/{sample_topic.id}/sources/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/abc123",
        "https://vimeo.com/123456789",
        "https://www.tiktok.com/@user/video/123",
        "https://twitter.com/i/status/123",
        "https://x.com/i/status/123",
        "https://open.spotify.com/track/abc",
        "https://soundcloud.com/artist/track",
        "https://example.com/video.mp4",
        "https://example.com/audio.mp3",
        "https://example.com/clip.webm",
    ],
)
async def test_upload_url_source_rejects_video_audio(
    client: AsyncClient, sample_topic: Topic, url: str
):
    """POST with a video/audio URL must return 422 before any background task is created."""
    response = await client.post(
        f"/topics/{sample_topic.id}/sources",
        data={
            "source_type": "url",
            "name": "Unsupported",
            "content": url,
        },
    )
    assert response.status_code == 422, f"Expected 422 for {url}, got {response.status_code}"
    detail = response.json()["detail"]
    assert "not supported" in detail.lower(), f"Unexpected detail: {detail}"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("report.pdf", "pdf"),
        ("Notes.DOCX", "docx"),
        ("sheet.xlsx", "xlsx"),
        ("readme.md", "text"),
        ("plain.txt", "text"),
        ("scan.JPEG", "image"),
    ],
)
def test_resolve_file_source_type(filename: str, expected: str):
    from app.routers.sources import _resolve_file_source_type

    assert _resolve_file_source_type(filename) == expected


@pytest.mark.asyncio
async def test_upload_file_source_resolves_type_from_extension(
    client: AsyncClient, sample_topic: Topic
):
    """The web UI posts source_type="file"; the parser type comes from the extension."""
    from unittest.mock import AsyncMock, patch

    with patch("app.routers.sources._run_ingest_background", new_callable=AsyncMock) as ingest:
        response = await client.post(
            f"/topics/{sample_topic.id}/sources",
            data={"source_type": "file", "name": "notes.md"},
            files={"file": ("notes.md", b"# Hello\n\nSome notes.", "text/markdown")},
        )
    assert response.status_code == 202
    assert "task_id" in response.json()
    assert ingest.call_args.kwargs["source_type"] == "text"


@pytest.mark.asyncio
async def test_upload_file_source_rejects_unsupported_extension(
    client: AsyncClient, sample_topic: Topic
):
    response = await client.post(
        f"/topics/{sample_topic.id}/sources",
        data={"source_type": "file", "name": "tool.exe"},
        files={"file": ("tool.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 422
    assert "Unsupported file type" in response.json()["detail"]
