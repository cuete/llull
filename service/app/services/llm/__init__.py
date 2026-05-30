"""LLM adapter factory."""
from __future__ import annotations

from app.services.llm.anthropic import AnthropicAdapter
from app.services.llm.base import LLMAdapter
from app.services.llm.ollama import OllamaAdapter
from app.services.llm.openai import OpenAIAdapter


def create_llm_adapter(
    provider: str,
    model: str,
    api_key: str = "",
    ollama_base_url: str = "http://localhost:11434",
    azure_endpoint: str | None = None,
    azure_api_version: str = "2024-02-01",
) -> LLMAdapter:
    """Factory function to create the appropriate LLM adapter."""
    match provider.lower():
        case "openai":
            return OpenAIAdapter(
                api_key=api_key,
                model=model,
                azure_endpoint=azure_endpoint or None,
                azure_api_version=azure_api_version,
            )
        case "anthropic":
            return AnthropicAdapter(api_key=api_key, model=model)
        case "ollama":
            return OllamaAdapter(base_url=ollama_base_url, model=model)
        case _:
            raise ValueError(f"Unknown LLM provider: {provider!r}")


__all__ = ["LLMAdapter", "OpenAIAdapter", "AnthropicAdapter", "OllamaAdapter", "create_llm_adapter"]
