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

from app.config import Settings, get_cached_settings
from app.database import get_db
from app.models.source import Chunk, Source
from app.models.topic import Conversation, Topic
from app.routers.deps import get_current_user, get_embedding_service, get_llm_adapter
from app.models.graph import Node, Edge
from app.schemas.topic import ChatRequest, ConversationResponse
from app.services.embeddings import EmbeddingService
from app.services.llm.base import LLMAdapter
from app.services.prompt import (
    LLULL_SYSTEM_PROMPT,
    build_chat_context,
    count_tokens,
    source_token_budget,
)
from app.services.retrieval import ExcerptChunk, build_excerpt_context

log = structlog.get_logger()

router = APIRouter(prefix="/topics/{topic_id}", tags=["chat"])


@router.get("/chat", response_model=list[ConversationResponse])
async def get_chat_history(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Conversation]:
    await _get_topic_or_404(db, topic_id)
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
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    settings: Settings = Depends(get_cached_settings),
) -> StreamingResponse:
    topic = await _get_topic_or_404(db, topic_id)

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

    # Determine if this is the first message (only the user message we just added)
    is_first_message = len([m for m in history if m.role == "assistant"]) == 0

    # Build messages
    conversation_dicts = [{"role": m.role, "content": m.content} for m in history]

    # Sources too large for the context: send excerpts from across the whole of them
    # (plus the concept map) instead of letting build_chat_context keep only the start.
    source_budget = source_token_budget(
        LLULL_SYSTEM_PROMPT, topic.context_summary, conversation_dicts, settings.chat_context_tokens
    )
    if sum(count_tokens(t) for t in source_texts) > source_budget:
        source_texts = [
            await _build_excerpt_source_text(
                db, topic_id, body.message, sources, embedding_service, source_budget
            )
        ]

    messages = build_chat_context(
        system_prompt=LLULL_SYSTEM_PROMPT,
        context_summary=topic.context_summary,
        conversation_history=conversation_dicts,
        source_texts=source_texts,
        max_tokens=settings.chat_context_tokens,
    )

    # Build DB-sourced mermaid block for first message (replaces any LLM-generated chart)
    mermaid_block: str | None = None
    if is_first_message:
        nodes_result = await db.execute(
            select(Node).where(Node.topic_id == topic_id).order_by(Node.created_at).limit(8)
        )
        top_nodes = list(nodes_result.scalars().all())
        if top_nodes:
            node_ids = {n.id for n in top_nodes}
            edges_result = await db.execute(
                select(Edge).where(
                    Edge.from_node_id.in_(node_ids),
                    Edge.to_node_id.in_(node_ids),
                )
            )
            edges = list(edges_result.scalars().all())
            mermaid_block = _build_mermaid_block(top_nodes, edges)

    # Commit user message before streaming
    await db.commit()

    # Use the same factory as the get_db override
    from app.database import get_session_factory as _get_sf

    def _get_factory():
        try:
            return _get_sf()
        except RuntimeError:
            return None

    factory = _get_factory()

    return StreamingResponse(
        _stream_chat(topic_id, messages, llm, factory, mermaid_block),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _build_excerpt_source_text(
    db: AsyncSession,
    topic_id: str,
    question: str,
    sources: list[Source],
    embedding_service: EmbeddingService,
    token_budget: int,
) -> str:
    source_names = {s.id: s.name for s in sources}
    source_position = {s.id: i for i, s in enumerate(sources)}

    chunks_result = await db.execute(select(Chunk).where(Chunk.topic_id == topic_id))
    chunks = sorted(
        (c for c in chunks_result.scalars().all() if c.source_id in source_names),
        key=lambda c: (source_position[c.source_id], c.order),
    )
    nodes_result = await db.execute(
        select(Node).where(Node.topic_id == topic_id).order_by(Node.created_at)
    )

    return await build_excerpt_context(
        question=question,
        chunks=[
            ExcerptChunk(
                source_name=source_names[c.source_id],
                order=c.order,
                text=c.text,
                embedding=embedding_service.deserialize(c.embedding_json)
                if c.embedding_json
                else None,
            )
            for c in chunks
        ],
        concepts=[(n.label, n.description or "") for n in nodes_result.scalars().all()],
        embedding_service=embedding_service,
        token_budget=token_budget,
    )


def _build_mermaid_block(nodes: list[Node], edges: list[Edge]) -> str:
    """Build a mermaid graph LR block from nodes and edges.

    Uses short sequential IDs (n0, n1, ...) instead of UUIDs so the
    rendered diagram shows clean labels rather than raw UUID strings.
    """
    lines = ["graph LR"]
    # Map node.id -> safe short id for mermaid
    id_map: dict[str, str] = {}
    for i, node in enumerate(nodes):
        safe_id = f"n{i}"
        id_map[node.id] = safe_id
        safe_label = node.label.replace('"', '').replace('[', '').replace(']', '')[:35]
        lines.append(f'  {safe_id}("{safe_label}")')
    for edge in edges:
        from_id = id_map.get(edge.from_node_id)
        to_id = id_map.get(edge.to_node_id)
        if from_id and to_id:
            arrow = "-->" if edge.type == "hierarchical" else "---"
            lines.append(f"  {from_id} {arrow} {to_id}")
    graph_def = "\n".join(lines)
    return f"\n\n```mermaid\n{graph_def}\n```"


async def _stream_chat(
    topic_id: str,
    messages: list[dict],
    llm: LLMAdapter,
    factory,
    mermaid_block: str | None = None,
):
    """SSE generator for chat streaming."""
    assistant_content = ""
    message_id = str(uuid.uuid4())

    try:
        # Buffer full LLM response so we can strip any mermaid the LLM generates spontaneously
        raw_content = ""
        async for token in await llm.complete(messages, stream=True):
            raw_content += token

        # Strip LLM-generated mermaid blocks — the DB-sourced one will be appended instead
        import re as _re
        clean_content = _re.sub(r"```mermaid[\s\S]*?```", "", raw_content).strip()

        # Stream the cleaned text to the client
        assistant_content = clean_content
        data = json.dumps({"text": clean_content})
        yield f"event: token\ndata: {data}\n\n"

        # Append DB-sourced mermaid block on first message if available
        if mermaid_block:
            assistant_content += mermaid_block
            data = json.dumps({"text": mermaid_block})
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


async def _get_topic_or_404(db: AsyncSession, topic_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
