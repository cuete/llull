"""Analysis router — L0 analysis and zoom operations with SSE."""
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_cached_settings
from app.database import get_db
from app.models.graph import Node
from app.models.source import Source
from app.models.topic import Topic
from app.routers.deps import get_current_user, get_embedding_service, get_llm_adapter
from app.services.analysis import AnalysisService
from app.services.embeddings import EmbeddingService
from app.services.llm.base import LLMAdapter

log = structlog.get_logger()

router = APIRouter(prefix="/topics/{topic_id}", tags=["analysis"])

KEEPALIVE_SECONDS = 15.0


@router.post("/analyze")
async def analyze_l0(
    topic_id: str,
    source_id: str | None = None,
    force: bool = False,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMAdapter = Depends(get_llm_adapter),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    settings: Settings = Depends(get_cached_settings),
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
        _with_keepalive(
            _stream_analysis(
                topic_id, sources, _analysis_service(db, llm, embedding_service, settings), db
            )
        ),
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
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    settings: Settings = Depends(get_cached_settings),
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
        _with_keepalive(
            _stream_zoom(topic_id, node, _analysis_service(db, llm, embedding_service, settings), db)
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _with_keepalive(events, interval: float = KEEPALIVE_SECONDS):
    """
    Pass SSE events through, sending a comment line while the source is silent.

    A map build or zoom is one long LLM call; without traffic the ingress in front of
    the app closes the idle connection before the result arrives.
    """
    iterator = events.__aiter__()
    pending: asyncio.Future | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield ": keepalive\n\n"
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            pending = None
            yield event
    finally:
        if pending is not None and not pending.done():
            pending.cancel()


def _analysis_service(
    db: AsyncSession, llm: LLMAdapter, embedding_service: EmbeddingService, settings: Settings
) -> AnalysisService:
    return AnalysisService(
        db=db,
        llm=llm,
        embeddings=embedding_service,
        l0_full_read_tokens=settings.l0_full_read_tokens,
        l0_sample_share=settings.l0_sample_share,
        l0_sample_max_tokens=settings.l0_sample_max_tokens,
        zoom_read_tokens=settings.zoom_read_tokens,
    )


async def _stream_analysis(
    topic_id: str,
    sources: list[Source],
    svc: AnalysisService,
    db: AsyncSession,
):
    """SSE generator for L0 analysis."""
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
    svc: AnalysisService,
    db: AsyncSession,
):
    """SSE generator for zoom operation."""
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
