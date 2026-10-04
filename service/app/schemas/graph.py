"""Graph schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NodeResponse(BaseModel):
    id: str
    topic_id: str
    source_id: str
    label: str
    description: str
    status: Literal["unexplored", "zoomed"]
    level: int = 0
    parent_id: str | None = None
    coverage: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EdgeResponse(BaseModel):
    id: str
    from_node_id: str
    to_node_id: str
    type: Literal["relational", "hierarchical", "causal"]
    weight: float
    confidence: float
    basis: Literal["sampled", "read", "suggested"] = "read"
    status: Literal["active", "unsupported"] = "active"
    evidence: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EdgeUpdate(BaseModel):
    weight: float = Field(..., ge=0.0, le=1.0)


class GraphResponse(BaseModel):
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
