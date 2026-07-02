"""Document router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.document import Document, DocumentBlock
from app.models.topic import Topic
from app.routers.deps import get_current_user
from app.schemas.document import DocumentBlockCreate, DocumentBlockResponse, DocumentBlockUpdate, DocumentResponse

router = APIRouter(prefix="/topics/{topic_id}", tags=["document"])


@router.get("/document", response_model=DocumentResponse)
async def get_document(
    topic_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Document:
    await _get_topic_or_404(db, topic_id, user_id)
    result = await db.execute(
        select(Document)
        .where(Document.topic_id == topic_id)
        .options(selectinload(Document.blocks))
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        # Create empty document for new topics instead of returning 404
        doc = Document(topic_id=topic_id)
        db.add(doc)
        await db.flush()
        # Re-query with selectinload so blocks relationship is eagerly loaded
        result = await db.execute(
            select(Document)
            .where(Document.topic_id == topic_id)
            .options(selectinload(Document.blocks))
        )
        doc = result.scalar_one()
    return doc


@router.patch("/document/blocks/{block_id}", response_model=DocumentBlockResponse)
async def update_block(
    topic_id: str,
    block_id: str,
    body: DocumentBlockUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentBlock:
    await _get_topic_or_404(db, topic_id, user_id)

    # Verify block belongs to this topic's document
    result = await db.execute(
        select(DocumentBlock)
        .join(Document, DocumentBlock.document_id == Document.id)
        .where(DocumentBlock.id == block_id, Document.topic_id == topic_id)
    )
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")

    block.content_md = body.content_md
    await db.flush()
    await db.refresh(block)
    return block


@router.post("/document/blocks", response_model=DocumentBlockResponse, status_code=201)
async def create_block(
    topic_id: str,
    body: DocumentBlockCreate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentBlock:
    """Append a new block to the topic document (creates document if missing)."""
    await _get_topic_or_404(db, topic_id, user_id)

    # Ensure document exists
    result = await db.execute(
        select(Document)
        .where(Document.topic_id == topic_id)
        .options(selectinload(Document.blocks))
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        doc = Document(topic_id=topic_id)
        db.add(doc)
        await db.flush()
        result = await db.execute(
            select(Document)
            .where(Document.topic_id == topic_id)
            .options(selectinload(Document.blocks))
        )
        doc = result.scalar_one()

    # Determine order (append after last block)
    next_order = body.order if body.order is not None else len(doc.blocks)

    block = DocumentBlock(
        document_id=doc.id,
        content_md=body.content_md,
        order=next_order,
    )
    db.add(block)
    await db.flush()
    await db.refresh(block)
    return block


async def _get_topic_or_404(db: AsyncSession, topic_id: str, user_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
