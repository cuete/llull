"""Topic and Conversation schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TopicCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)


class TopicPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=500)
    context_summary: str | None = None


class TopicResponse(BaseModel):
    id: str
    user_id: str
    title: str
    context_summary: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: str
    topic_id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
