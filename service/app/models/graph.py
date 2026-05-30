"""Node and Edge models for the knowledge graph."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # Embedding stored as JSON blob — sqlite-vec integration point
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("unexplored", "zoomed", name="node_status"),
        nullable=False,
        default="unexplored",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    topic: Mapped["Topic"] = relationship("Topic", back_populates="nodes")  # noqa: F821
    source: Mapped["Source"] = relationship("Source", back_populates="nodes")  # noqa: F821
    outgoing_edges: Mapped[list["Edge"]] = relationship(
        "Edge", foreign_keys="Edge.from_node_id", back_populates="from_node", cascade="all, delete-orphan"
    )
    incoming_edges: Mapped[list["Edge"]] = relationship(
        "Edge", foreign_keys="Edge.to_node_id", back_populates="to_node", cascade="all, delete-orphan"
    )


class Edge(Base):
    __tablename__ = "edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    from_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_node_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        Enum("relational", "hierarchical", "causal", name="edge_type"), nullable=False
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    from_node: Mapped["Node"] = relationship(
        "Node", foreign_keys=[from_node_id], back_populates="outgoing_edges"
    )
    to_node: Mapped["Node"] = relationship(
        "Node", foreign_keys=[to_node_id], back_populates="incoming_edges"
    )
