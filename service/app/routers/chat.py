"""Chat router with SSE streaming."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.source import Source
from app.models.topic import Conversation, Topic
from app.routers.deps import get_current_user, get_llm_adapter
from app.schemas.topic import ChatRequest, ConversationResponse
from app.services.llm.base import LLMAdapter
from app.services.prompt import LLULL_SYSTEM_PROMPT, build_chat_context

log = structlog.get_logger()

router = APIRouter(prefix="/topics/{topic_id}", tags=["chat"])


@router.get("/chat", response_model=list[ConversationResponse])
async def get_chat_history(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Conversation]:
    await _get_topic_or_404(db, topic_id, user_id)
    result = await db.execute(
        select(Conversation)
        .where(Conversation.topic_id == topic_id)
        .order_by(Conversation.created_at)
    )
    return list(result.scalars().all())


@router.post("/chat")
async def chat(
    topic_id: str,
    body: ChatRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMAdapter = Depends(get_llm_adapter),
) -> StreamingResponse:
    topic = await _get_topic_or_404(db, topic_id, user_id)

    # Persist user message
    user_msg = Conversation(
        id=str(uuid.uuid4()),
        topic_id=topic_id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.flush()

    # Load conversation history
    history_result = await db.execute(
        select(Conversation)
        .where(Conversation.topic_id == topic_id)
        .order_by(Conversation.created_at)
    )
    history = list(history_result.scalars().all())

    # Load sources
    sources_result = await db.execute(
        select(Source).where(Source.topic_id == topic_id)
    )
    sources = list(sources_result.scalars().all())
    source_texts = [s.extracted_text for s in sources if s.extracted_text]

    # Build messages
    conversation_dicts = [{"role": m.role, "content": m.content} for m in history]
    messages = build_chat_context(
        system_prompt=LLULL_SYSTEM_PROMPT,
        context_summary=topic.context_summary,
        conversation_history=conversation_dicts,
        source_texts=source_texts,
    )

    # Commit user message before streaming
    await db.commit()

    # Capture the session factory from this request's DI context
    from sqlalchemy.ext.asyncio import async_sessionmaker
    session_factory = db.get_bind().__class__  # type: ignore

    # Use the same factory as the get_db override
    from app.database import get_session_factory as _get_sf

    def _get_factory():
        try:
            return _get_sf()
        except RuntimeError:
            return None

    factory = _get_factory()

    return StreamingResponse(
        _stream_chat(topic_id, messages, llm, factory),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_chat(
    topic_id: str,
    messages: list[dict],
    llm: LLMAdapter,
    factory,
):
    """SSE generator for chat streaming."""
    assistant_content = ""
    message_id = str(uuid.uuid4())

    try:
        async for token in await llm.complete(messages, stream=True):
            assistant_content += token
            data = json.dumps({"text": token})
            yield f"event: token\ndata: {data}\n\n"

        # Persist assistant message if factory available
        if factory is not None:
            try:
                async with factory() as db:
                    assistant_msg = Conversation(
                        id=message_id,
                        topic_id=topic_id,
                        role="assistant",
                        content=assistant_content,
                    )
                    db.add(assistant_msg)
                    await db.commit()
            except Exception as e:
                log.warning("chat_persist_failed", error=str(e))

        done_data = json.dumps({"message_id": message_id})
        yield f"event: done\ndata: {done_data}\n\n"

    except Exception as e:
        log.error("chat_stream_error", error=str(e))
        error_data = json.dumps({"code": "STREAM_FAILED", "message": str(e)})
        yield f"event: error\ndata: {error_data}\n\n"


async def _get_topic_or_404(db: AsyncSession, topic_id: str, user_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
