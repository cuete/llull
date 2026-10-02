"""FastAPI application factory with lifespan management."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_cached_settings
from app.database import close_db, init_db
from app.routers import analysis, chat, document, export, fact_check, graph, health, sources, tasks, topics

log = structlog.get_logger()

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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

    # Read-only mode: block writes when enabled, leave GET/HEAD/OPTIONS (and
    # CORS preflight) untouched so exploring a topic keeps working.
    @app.middleware("http")
    async def read_only_guard(request: Request, call_next):
        if get_cached_settings().read_only and request.method in _MUTATING_METHODS:
            return JSONResponse(
                status_code=403,
                content={"detail": "Server is in read-only mode. Create/update actions are disabled."},
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

    # Serve the built frontend (web/dist), if present, from the same app/origin.
    # Mounted last so it never shadows the API routes above. Known limitation: a
    # hard refresh on /topics/{id} hits the API's JSON route instead of the SPA
    # (both use that exact path shape) — normal in-app navigation is unaffected.
    if settings.static_dir:
        static_dir = Path(settings.static_dir)
        index_html = static_dir / "index.html"

        @app.get("/", include_in_schema=False)
        async def serve_spa_root() -> FileResponse:
            return FileResponse(index_html)

        app.mount("/", StaticFiles(directory=static_dir), name="static")

    return app


app = create_app()
