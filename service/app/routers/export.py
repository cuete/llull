"""Export router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.document import Document
from app.models.topic import Topic
from app.routers.deps import get_current_user
from app.services.export import ExportService

router = APIRouter(prefix="/topics/{topic_id}", tags=["export"])

ALLOWED_FORMATS = {"pdf", "md", "html", "txt", "zip"}


@router.get("/export")
async def export_document(
    topic_id: str,
    format: str = Query(..., alias="format"),
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if format.lower() not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Allowed: {', '.join(ALLOWED_FORMATS)}",
        )

    await _get_topic_or_404(db, topic_id, user_id)

    result = await db.execute(
        select(Document)
        .where(Document.topic_id == topic_id)
        .options(selectinload(Document.blocks))
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    svc = ExportService()
    content_bytes, mime_type = await svc.export(doc, format)

    extension_map = {"md": "md", "txt": "txt", "html": "html", "pdf": "pdf", "zip": "zip"}
    filename = f"document.{extension_map[format.lower()]}"

    return Response(
        content=content_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _get_topic_or_404(db: AsyncSession, topic_id: str, user_id: str) -> Topic:
    result = await db.execute(
        select(Topic).where(Topic.id == topic_id, Topic.user_id == user_id)
    )
    topic = result.scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
