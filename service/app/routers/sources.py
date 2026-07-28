"""Sources router."""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.source import Source
from app.models.task import Task
from app.models.topic import Topic
from app.routers.deps import get_current_user, get_embedding_service, get_llm_adapter
from app.schemas.source import SourcePatch, SourceResponse, TaskCreatedResponse
from app.parsers.url import _check_unsupported_url
from app.services.embeddings import EmbeddingService
from app.services.ingest import IngestService
from app.services.llm.base import LLMAdapter

router = APIRouter(prefix="/topics/{topic_id}/sources", tags=["sources"])


async def _get_topic_or_404(db: AsyncSession, topic_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Source]:
    await _get_topic_or_404(db, topic_id)
    result = await db.execute(
        select(Source).where(Source.topic_id == topic_id).order_by(Source.created_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=TaskCreatedResponse, status_code=202)
async def upload_source(
    topic_id: str,
    source_type: str = Form(...),
    name: str = Form(...),
    content: str | None = Form(None),
    file: UploadFile | None = File(None),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    llm: LLMAdapter = Depends(get_llm_adapter),
) -> dict:
    await _get_topic_or_404(db, topic_id)

    # Reject unsupported URL types (video/audio) before queuing any background work
    if source_type == "url" and content:
        try:
            _check_unsupported_url(content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Create task record
    task = Task(
        id=str(uuid.uuid4()),
        user_id=user_id,
        topic_id=topic_id,
        type="source_ingest",
        status="pending",
        progress=0,
    )
    db.add(task)
    await db.flush()
    task_id = task.id

    # Save file if provided
    temp_path: Path | None = None
    if file is not None:
        import tempfile

        suffix = Path(file.filename or "upload").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content_bytes = await file.read()
            tmp.write(content_bytes)
            temp_path = Path(tmp.name)

    # Commit the task record NOW so the background task can safely fetch it
    # (get_db() commits after yield, but background task runs concurrently)
    await db.commit()

    # Launch background ingestion
    asyncio.create_task(
        _run_ingest_background(
            topic_id=topic_id,
            source_type=source_type,
            name=name,
            content=content,
            temp_path=temp_path,
            task_id=task_id,
            embedding_service=embedding_service,
            llm=llm,
        )
    )

    return {"task_id": task_id}


async def _run_ingest_background(
    topic_id: str,
    source_type: str,
    name: str,
    content: str | None,
    temp_path: Path | None,
    task_id: str,
    embedding_service: EmbeddingService,
    llm: LLMAdapter | None = None,
    session_factory=None,
) -> None:
    """Background ingestion task."""
    from app.config import get_cached_settings

    settings = get_cached_settings()

    if session_factory is None:
        from app.database import get_session_factory
        session_factory = get_session_factory()

    factory = session_factory

    async with factory() as db:
        try:
            # Re-fetch task in this session
            task_result = await db.execute(select(Task).where(Task.id == task_id))
            task = task_result.scalar_one()

            svc = IngestService(
                db=db,
                embedding_service=embedding_service,
                storage_backend=settings.storage_backend,
                local_storage_path=settings.local_storage_path,
                azure_connection_string=settings.azure_storage_connection_string,
                azure_container=settings.azure_storage_container,
                llm=llm,
            )

            if source_type == "url" and content:
                await svc.ingest_url(topic_id, name, content, task)
            elif source_type == "text" and content:
                await svc.ingest_text(topic_id, name, content, task)
            elif temp_path is not None:
                await svc.ingest_file(topic_id, source_type, name, temp_path, task)
            else:
                task.status = "failed"
                task.error = "No content or file provided"
                await db.flush()

            await db.commit()
        except Exception as e:
            await db.rollback()
            # Try to mark task as failed
            async with session_factory() as err_db:
                try:
                    task_result = await err_db.execute(select(Task).where(Task.id == task_id))
                    task = task_result.scalar_one_or_none()
                    if task:
                        task.status = "failed"
                        task.error = str(e)
                        await err_db.commit()
                except Exception:
                    pass
        finally:
            if temp_path and temp_path.exists():
                temp_path.unlink(missing_ok=True)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    topic_id: str,
    source_id: str,
    body: SourcePatch,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Source:
    await _get_topic_or_404(db, topic_id)
    source = await _get_source_or_404(db, source_id, topic_id)

    if body.name is not None:
        source.name = body.name

    await db.flush()
    await db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    topic_id: str,
    source_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_topic_or_404(db, topic_id)
    source = await _get_source_or_404(db, source_id, topic_id)
    await db.delete(source)
    await db.flush()


async def _get_source_or_404(db: AsyncSession, source_id: str, topic_id: str) -> Source:
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.topic_id == topic_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source
