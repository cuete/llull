"""Tests for LLM adapters."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm import create_llm_adapter
from app.services.llm.anthropic import AnthropicAdapter
from app.services.llm.ollama import OllamaAdapter
from app.services.llm.openai import OpenAIAdapter


def test_create_llm_adapter_anthropic():
    adapter = create_llm_adapter("anthropic", "claude-sonnet-4-5", api_key="test")
    assert isinstance(adapter, AnthropicAdapter)
    assert adapter.model_name == "claude-sonnet-4-5"


def test_create_llm_adapter_openai():
    adapter = create_llm_adapter("openai", "gpt-4o", api_key="test")
    assert isinstance(adapter, OpenAIAdapter)
    assert adapter.model_name == "gpt-4o"


def test_create_llm_adapter_ollama():
    adapter = create_llm_adapter("ollama", "llama3")
    assert isinstance(adapter, OllamaAdapter)
    assert adapter.model_name == "llama3"


def test_create_llm_adapter_unknown():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        create_llm_adapter("unknown", "model")


@pytest.mark.asyncio
async def test_anthropic_adapter_embed_not_implemented():
    adapter = AnthropicAdapter(api_key="test")
    with pytest.raises(NotImplementedError):
        await adapter.embed(["text"])


@pytest.mark.asyncio
async def test_ollama_adapter_complete_batch():
    """OllamaAdapter batch complete via mocked httpx."""
    import httpx
    import respx

    response_data = {"message": {"content": "Hello from Ollama"}}

    with respx.mock:
        respx.post("http://localhost:11434/api/chat").mock(
            return_value=httpx.Response(200, json=response_data)
        )

        adapter = OllamaAdapter(base_url="http://localhost:11434", model="llama3")
        result = ""
        async for token in await adapter.complete(
            [{"role": "user", "content": "hi"}], stream=False
        ):
            result += token

    assert result == "Hello from Ollama"


@pytest.mark.asyncio
async def test_ollama_adapter_embed():
    """OllamaAdapter embed via mocked httpx."""
    import httpx
    import respx

    embedding = [0.1, 0.2, 0.3]
    response_data = {"embedding": embedding}

    with respx.mock:
        respx.post("http://localhost:11434/api/embeddings").mock(
            return_value=httpx.Response(200, json=response_data)
        )

        adapter = OllamaAdapter(base_url="http://localhost:11434", model="llama3")
        result = await adapter.embed(["hello"])

    assert result == [embedding]


@pytest.mark.asyncio
async def test_openai_adapter_missing_import():
    """OpenAIAdapter raises ImportError when openai not available."""
    import sys
    import builtins

    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "openai":
            raise ImportError("No module named 'openai'")
        return original_import(name, *args, **kwargs)

    adapter = OpenAIAdapter(api_key="test", model="gpt-4o")
    adapter._client = None  # Reset cached client

    with patch("builtins.__import__", side_effect=mock_import):
        with pytest.raises(ImportError, match="openai package is required"):
            adapter._get_client()
