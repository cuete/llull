"""Analysis router — L0 analysis and zoom operations with SSE."""
from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.graph import Node
from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import get_current_user, get_llm_adapter
from app.services.analysis import AnalysisService
from app.services.llm.base import LLMAdapter

log = structlog.get_logger()

router = APIRouter(prefix="/topics/{topic_id}", tags=["analysis"])


@router.post("/analyze")
async def analyze_l0(
    topic_id: str,
    source_id: str | None = None,
    force: bool = False,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMAdapter = Depends(get_llm_adapter),
) -> StreamingResponse:
    """
    Level-0 analysis: extract knowledge graph from sources.
    Streams SSE events. Pass ?force=true to re-analyze existing topics.
    """
    await _get_topic_or_404(db, topic_id)

    # Idempotency: skip LLM if nodes already exist (unless forced)
    if not force:
        existing = await db.execute(
            select(Node).where(Node.topic_id == topic_id).limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=409,
                detail="Topic already analyzed. View results at /graph, or pass ?force=true to re-analyze.",
            )

    # Get sources to analyze
    if source_id:
        source_result = await db.execute(
            select(Source).where(Source.id == source_id, Source.topic_id == topic_id)
        )
        source = source_result.scalar_one_or_none()
        if source is None:
            raise HTTPException(status_code=404, detail="Source not found")
        sources = [source]
    else:
        sources_result = await db.execute(
            select(Source).where(Source.topic_id == topic_id)
        )
        sources = list(sources_result.scalars().all())

    if not sources:
        raise HTTPException(status_code=400, detail="No sources to analyze")

    return StreamingResponse(
        _stream_analysis(topic_id, sources, db, llm),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/zoom/{node_id}")
async def zoom_node(
    topic_id: str,
    node_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMAdapter = Depends(get_llm_adapter),
) -> StreamingResponse:
    """
    Zoom into a node to generate sub-concepts.
    Streams SSE events.
    """
    await _get_topic_or_404(db, topic_id)

    node_result = await db.execute(
        select(Node).where(Node.id == node_id, Node.topic_id == topic_id)
    )
    node = node_result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    return StreamingResponse(
        _stream_zoom(topic_id, node, db, llm),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream_analysis(
    topic_id: str,
    sources: list[Source],
    db: AsyncSession,
    llm: LLMAdapter,
):
    """SSE generator for L0 analysis."""
    svc = AnalysisService(db=db, llm=llm)
    try:
        for source in sources:
            async for event_type, data in svc.analyze_l0(topic_id, source):
                yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
            await db.commit()  # commit per-source so client disconnect doesn't lose work
    except Exception as e:
        log.error("analysis_stream_error", error=str(e))
        await db.rollback()
        error_data = json.dumps({"code": "ANALYSIS_FAILED", "message": str(e)})
        yield f"event: error\ndata: {error_data}\n\n"


async def _stream_zoom(
    topic_id: str,
    node: Node,
    db: AsyncSession,
    llm: LLMAdapter,
):
    """SSE generator for zoom operation."""
    svc = AnalysisService(db=db, llm=llm)
    try:
        async for event_type, data in svc.zoom(topic_id, node):
            yield f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        await db.commit()
    except Exception as e:
        log.error("zoom_stream_error", error=str(e))
        await db.rollback()
        error_data = json.dumps({"code": "ZOOM_FAILED", "message": str(e)})
        yield f"event: error\ndata: {error_data}\n\n"


async def _get_topic_or_404(db: AsyncSession, topic_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
