"""Source model."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(
        Enum("pdf", "docx", "xlsx", "text", "url", "image", name="source_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    blob_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    # Quality ratings (populated by RatingService during ingest)
    ai_suspicion: Mapped[int | None] = mapped_column(nullable=True)
    ai_suspicion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    quality_score: Mapped[int | None] = mapped_column(nullable=True)
    quality_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    fact_check_result: Mapped[str | None] = mapped_column(Text, nullable=True)   # JSON string
    fact_check_score: Mapped[int | None] = mapped_column(nullable=True)           # 0-100

    topic: Mapped["Topic"] = relationship("Topic", back_populates="sources")  # noqa: F821
    nodes: Mapped[list["Node"]] = relationship(  # noqa: F821
        "Node", back_populates="source", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="source", cascade="all, delete-orphan"
    )
    sections: Mapped[list["Section"]] = relationship(
        "Section", cascade="all, delete-orphan"
    )
    document_blocks: Mapped[list["DocumentBlock"]] = relationship(  # noqa: F821
        "DocumentBlock", back_populates="source"
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Embedding stored as JSON blob (float list) — sqlite-vec integration would use a vector column
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column(nullable=False, default=0)
    section_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    source: Mapped["Source"] = relationship("Source", back_populates="chunks")


class Section(Base):
    """A run of consecutive chunks of a source: a chapter, a headed part, or a fixed window."""

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order: Mapped[int] = mapped_column(nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # Front/back matter (contents, notes, bibliography, index): never mapped into nodes
    is_boilerplate: Mapped[bool] = mapped_column(nullable=False, default=False)
