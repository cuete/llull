"""Health check endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_cached_settings

router = APIRouter()


@router.get("/health")
async def health(settings: Settings = Depends(get_cached_settings)) -> dict:
    """Simple health check."""
    return {
        "status": "ok",
        "read_only": settings.read_only,
        "auth_enabled": settings.auth_enabled,
    }
