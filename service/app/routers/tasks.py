"""Tasks router with SSE progress streaming."""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.task import Task
from app.routers.deps import get_current_user
from app.schemas.task import TaskResponse

log = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Task:
    task = await _get_task_or_404(db, task_id, user_id)
    return task


@router.get("/{task_id}/stream")
async def stream_task_progress(
    task_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """SSE stream for task progress polling."""
    task = await _get_task_or_404(db, task_id, user_id)

    # Capture factory from DI context
    from app.database import get_session_factory as _get_sf

    try:
        factory = _get_sf()
    except RuntimeError:
        factory = None

    return StreamingResponse(
        _poll_task(task_id, user_id, factory),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _poll_task(task_id: str, user_id: str, factory):
    """Poll task status and stream SSE events."""
    if factory is None:
        # Fallback: emit a single error event
        yield f"event: error\ndata: {json.dumps({'code': 'NO_DB'})}\n\n"
        return

    max_polls = 120  # 2 minutes max at 1s interval

    for _ in range(max_polls):
        async with factory() as db:
            result = await db.execute(
                select(Task).where(Task.id == task_id, Task.user_id == user_id)
            )
            task = result.scalar_one_or_none()
            if task is None:
                break

            data = json.dumps(
                {
                    "task_id": task.id,
                    "status": task.status,
                    "progress": task.progress,
                    "error": task.error,
                }
            )
            yield f"event: progress\ndata: {data}\n\n"

            if task.status in ("done", "failed"):
                final_data = json.dumps(
                    {
                        "task_id": task.id,
                        "status": task.status,
                        "result": task.result,
                        "error": task.error,
                    }
                )
                yield f"event: done\ndata: {final_data}\n\n"
                return

        await asyncio.sleep(1)

    yield f"event: error\ndata: {json.dumps({'code': 'TIMEOUT'})}\n\n"


async def _get_task_or_404(db: AsyncSession, task_id: str, user_id: str) -> Task:
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.user_id == user_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
