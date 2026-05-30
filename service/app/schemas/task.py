"""Task schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class TaskResponse(BaseModel):
    id: str
    user_id: str
    topic_id: str | None
    type: Literal["source_ingest", "analyze_l0", "zoom", "export"]
    status: Literal["pending", "running", "done", "failed"]
    progress: int
    result: Any | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
