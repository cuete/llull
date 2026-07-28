"""Topics CRUD router."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.topic import Topic
from app.routers.deps import get_current_user
from app.schemas.topic import TopicCreate, TopicPatch, TopicResponse

router = APIRouter(prefix="/topics", tags=["topics"])


@router.get("", response_model=list[TopicResponse])
async def list_topics(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Topic]:
    result = await db.execute(select(Topic).order_by(Topic.updated_at.desc()))
    return list(result.scalars().all())


@router.post("", response_model=TopicResponse, status_code=201)
async def create_topic(
    body: TopicCreate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Topic:
    topic = Topic(
        id=str(uuid.uuid4()),
        user_id=user_id,
        title=body.title,
    )
    db.add(topic)
    await db.flush()
    await db.refresh(topic)
    return topic


@router.get("/{topic_id}", response_model=TopicResponse)
async def get_topic(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Topic:
    topic = await _get_topic_or_404(db, topic_id)
    return topic


@router.patch("/{topic_id}", response_model=TopicResponse)
async def update_topic(
    topic_id: str,
    body: TopicPatch,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Topic:
    topic = await _get_topic_or_404(db, topic_id)

    if body.title is not None:
        topic.title = body.title
    if body.context_summary is not None:
        topic.context_summary = body.context_summary
    topic.updated_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(topic)
    return topic


@router.delete("/{topic_id}", status_code=204)
async def delete_topic(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    topic = await _get_topic_or_404(db, topic_id)
    await db.delete(topic)
    await db.flush()


async def _get_topic_or_404(db: AsyncSession, topic_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
