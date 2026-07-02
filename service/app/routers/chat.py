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
from app.models.graph import Node, Edge
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

    # Determine if this is the first message (only the user message we just added)
    is_first_message = len([m for m in history if m.role == "assistant"]) == 0

    # Build messages
    conversation_dicts = [{"role": m.role, "content": m.content} for m in history]
    messages = build_chat_context(
        system_prompt=LLULL_SYSTEM_PROMPT,
        context_summary=topic.context_summary,
        conversation_history=conversation_dicts,
        source_texts=source_texts,
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


async def _get_topic_or_404(db: AsyncSession, topic_id: str, user_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
