"""Source schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SourceUpload(BaseModel):
    """Used when creating a source from URL or text."""
    type: Literal["pdf", "docx", "xlsx", "text", "url", "image"]
    name: str = Field(..., min_length=1, max_length=500)
    # For URL type, content is the URL string
    # For text type, content is the text itself
    content: str | None = None


class SourcePatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=500)


class SourceResponse(BaseModel):
    id: str
    topic_id: str
    type: str
    name: str
    blob_url: str | None
    extracted_text: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskCreatedResponse(BaseModel):
    task_id: str
