"""Async SQLAlchemy database setup."""
from __future__ import annotations

import os
from pathlib import Path
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

log = structlog.get_logger()

# Will be set during app startup
_engine: AsyncEngine | None = None
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db() first.")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _async_session_factory is None:
        raise RuntimeError("Session factory not initialized. Call init_db() first.")
    return _async_session_factory


async def init_db(database_url: str) -> None:
    """Initialize database engine and create tables."""
    global _engine, _async_session_factory

    # Ensure data directory exists for SQLite
    if "sqlite" in database_url:
        db_path = database_url.replace("sqlite+aiosqlite:///", "")
        if db_path and not db_path.startswith(":"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_pre_ping=True,
    )
    _async_session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Import models so they register with Base metadata
    from app.models import document, graph, source, task, topic  # noqa: F401

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)

    log.info("database_initialized", url=database_url)


# Columns added to tables that already exist in deployed databases. create_all only
# creates missing tables, so these are added in place.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "chunks": {"section_id": "VARCHAR(36)"},
    "nodes": {
        "level": "INTEGER NOT NULL DEFAULT 0",
        "parent_id": "VARCHAR(36)",
        "coverage": "FLOAT",
    },
    "edges": {
        "basis": "VARCHAR(20) NOT NULL DEFAULT 'read'",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'active'",
        "evidence": "TEXT",
    },
}


def _add_missing_columns(conn) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(conn)
    for table, columns in _ADDED_COLUMNS.items():
        existing = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                log.info("database_column_added", table=table, column=name)


async def close_db() -> None:
    """Close database connection."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        log.info("database_closed")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
