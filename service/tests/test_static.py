"""Tests for serving the built frontend (web/dist) from the same app."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import get_cached_settings
from app.main import create_app


@pytest.mark.asyncio
async def test_serves_spa_index_and_assets():
    with tempfile.TemporaryDirectory() as tmp:
        static_dir = Path(tmp)
        (static_dir / "index.html").write_text("<html>llull spa</html>")
        assets_dir = static_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "app.js").write_text("console.log('hi')")

        settings = get_cached_settings()
        original = settings.static_dir
        settings.static_dir = str(static_dir)
        try:
            app = create_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                root = await client.get("/")
                assert root.status_code == 200
                assert "llull spa" in root.text

                asset = await client.get("/assets/app.js")
                assert asset.status_code == 200
                assert "console.log" in asset.text

                # API routes still take priority over the static mount
                health = await client.get("/health")
                assert health.status_code == 200
                assert health.json()["status"] == "ok"
        finally:
            settings.static_dir = original
