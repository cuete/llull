"""OpenAI / Azure OpenAI LLM adapter."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.llm.base import LLMAdapter

log = structlog.get_logger()


def _sync_openrouter_call(base_url: str, api_key: str, model: str, messages: list, max_tokens: int) -> str:
    """Synchronous OpenRouter call — runs in thread executor to avoid anyio DNS issues on Windows."""
    import httpx
    url = base_url.rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            content=json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens}),
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""


class OpenAIAdapter(LLMAdapter):
    """OpenAI or Azure OpenAI adapter."""

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        azure_endpoint: str | None = None,
        azure_api_version: str = "2024-02-01",
        base_url: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._azure_endpoint = azure_endpoint
        self._azure_api_version = azure_api_version
        self._base_url = base_url
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            try:
                import openai

                if self._azure_endpoint:
                    self._client = openai.AsyncAzureOpenAI(
                        api_key=self._api_key,
                        azure_endpoint=self._azure_endpoint,
                        api_version=self._azure_api_version,
                    )
                else:
                    self._client = openai.AsyncOpenAI(api_key=self._api_key)
            except ImportError as e:
                raise ImportError("openai package is required for OpenAIAdapter") from e
        return self._client

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
        log.info("llm_complete", provider="openai", model=self._model, stream=stream)

        if self._base_url:
            return self._openrouter_complete(messages, max_tokens)

        client = self._get_client()
        if stream:
            return self._stream_complete(client, messages, max_tokens)
        else:
            return self._batch_complete(client, messages, max_tokens)

    async def _openrouter_complete(
        self, messages: list[dict], max_tokens: int
    ) -> AsyncIterator[str]:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            _sync_openrouter_call,
            self._base_url,
            self._api_key,
            self._model,
            messages,
            max_tokens,
        )
        yield text

    async def _stream_complete(
        self, client: object, messages: list[dict], max_tokens: int
    ) -> AsyncIterator[str]:
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def _batch_complete(
        self, client: object, messages: list[dict], max_tokens: int
    ) -> AsyncIterator[str]:
        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            stream=False,
        )
        yield response.choices[0].message.content or ""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    )
    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [item.embedding for item in response.data]
