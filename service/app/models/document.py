"""Document and DocumentBlock models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    topic_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    route_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    topic: Mapped["Topic"] = relationship("Topic", back_populates="document")  # noqa: F821
    blocks: Mapped[list["DocumentBlock"]] = relationship(
        "DocumentBlock", back_populates="document", cascade="all, delete-orphan", order_by="DocumentBlock.order"
    )


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    content_md: Mapped[str] = mapped_column(Text, nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    document: Mapped["Document"] = relationship("Document", back_populates="blocks")
    source: Mapped["Source | None"] = relationship("Source", back_populates="document_blocks")  # noqa: F821
