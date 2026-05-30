"""Document schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocumentBlockResponse(BaseModel):
    id: str
    document_id: str
    source_id: str | None
    content_md: str
    order: int

    model_config = {"from_attributes": True}


class DocumentBlockUpdate(BaseModel):
    content_md: str


class DocumentResponse(BaseModel):
    id: str
    topic_id: str
    route_summary: str | None
    updated_at: datetime
    blocks: list[DocumentBlockResponse]

    model_config = {"from_attributes": True}
