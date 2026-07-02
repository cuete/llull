"""FastAPI application factory with lifespan management."""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_cached_settings
from app.database import close_db, init_db
from app.routers import analysis, chat, document, export, fact_check, graph, health, sources, tasks, topics

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    settings = get_cached_settings()

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.JSONRenderer(),
        ],
    )

    log.info("app_startup", env="local" if not settings.auth_enabled else "production")

    await init_db(settings.database_url)

    yield

    await close_db()
    log.info("app_shutdown")


def create_app() -> FastAPI:
    settings = get_cached_settings()

    app = FastAPI(
        title="Llull",
        description="Document analysis workspace with iterative semantic zoom",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def demo_mode_guard(request: Request, call_next):
        """Reject all mutating requests when DEMO_MODE is enabled."""
        if settings.demo_mode and request.method not in ("GET", "HEAD", "OPTIONS"):
            return JSONResponse(
                status_code=403,
                content={"detail": "Demo mode: this instance is read-only. Modifications are disabled."},
            )
        return await call_next(request)

    # Routers
    app.include_router(health.router)
    app.include_router(topics.router)
    app.include_router(sources.router)
    app.include_router(graph.router)
    app.include_router(chat.router)
    app.include_router(analysis.router)
    app.include_router(document.router)
    app.include_router(export.router)
    app.include_router(tasks.router)
    app.include_router(fact_check.router)

    return app


app = create_app()
