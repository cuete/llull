"""Application configuration via pydantic-settings."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Auth
    auth_enabled: bool = False
    aad_tenant_id: str = "test-tenant"
    aad_client_id: str = "test-client"
    # Account IDs (token `oid`) allowed to use the API when auth is enabled.
    # Empty means any account that can sign in is accepted.
    allowed_user_ids: list[str] = []

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/llull.db"

    # LLM
    llm_provider: Literal["openai", "anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-4-5"
    llm_api_key: str = ""
    llm_base_url: str = ""
    ollama_base_url: str = "http://localhost:11434"
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-02-01"

    # Storage
    storage_backend: Literal["azure", "local"] = "local"
    local_storage_path: str = "./data/uploads"
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "llull-sources"

    # Embeddings
    embedding_model: str = "all-mpnet-base-v2"

    # Search / Fact-check
    perplexity_api_key: str = ""

    # App
    debug: bool = False
    log_level: str = "INFO"
    read_only: bool = False
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080", "http://100.103.209.11:3000"]

    # Static frontend (set when the built web/ SPA is served from this same app, e.g. in Docker)
    static_dir: str = ""

    @field_validator("cors_origins", "allowed_user_ids", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [origin.strip() for origin in v.split(",")]
        return v


def get_settings() -> Settings:
    return Settings()


# Module-level singleton (lazy-initialized per request via Depends)
_settings: Settings | None = None


def get_cached_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
