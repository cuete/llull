"""Ollama local LLM adapter."""
from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.llm.base import LLMAdapter

log = structlog.get_logger()


class OllamaAdapter(LLMAdapter):
    """Ollama local model adapter."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def model_name(self) -> str:
        return self._model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def complete(
        self,
        messages: list[dict],
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        log.info("llm_complete", provider="ollama", model=self._model, stream=stream)
        if stream:
            return self._stream_complete(messages)
        else:
            return self._batch_complete(messages)

    async def _stream_complete(self, messages: list[dict]) -> AsyncIterator[str]:
        import json

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json={"model": self._model, "messages": messages, "stream": True},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            yield content

    async def _batch_complete(self, messages: list[dict]) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={"model": self._model, "messages": messages, "stream": False},
            )
            response.raise_for_status()
            data = response.json()
            yield data.get("message", {}).get("content", "")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings via Ollama's /api/embeddings endpoint."""
        embeddings = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                response = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data["embedding"])
        return embeddings
