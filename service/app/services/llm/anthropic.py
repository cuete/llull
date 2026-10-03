"""Anthropic LLM adapter."""
from __future__ import annotations

from collections.abc import AsyncIterator

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.llm.base import LLMAdapter

log = structlog.get_logger()


class AnthropicAdapter(LLMAdapter):
    """Anthropic Claude adapter."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5") -> None:
        self._model = model
        self._api_key = api_key
        self._client: object | None = None

    def _get_client(self) -> object:
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError as e:
                raise ImportError("anthropic package is required for AnthropicAdapter") from e
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
        # Current Claude models think by default and thinking counts against
        # max_tokens, so the cap needs headroom beyond the visible answer.
        max_tokens: int = 16000,
    ) -> AsyncIterator[str]:
        client = self._get_client()
        log.info("llm_complete", provider="anthropic", model=self._model, stream=stream)

        # Separate system message from conversation messages
        system_content = None
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                chat_messages.append(msg)

        if stream:
            return self._stream_complete(client, chat_messages, system_content, max_tokens)
        else:
            return self._batch_complete(client, chat_messages, system_content, max_tokens)

    async def _stream_complete(
        self,
        client: object,
        messages: list[dict],
        system: str | None,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        kwargs: dict = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if system:
            kwargs["system"] = system

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def _batch_complete(
        self,
        client: object,
        messages: list[dict],
        system: str | None,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        kwargs: dict = {"model": self._model, "messages": messages, "max_tokens": max_tokens}
        if system:
            kwargs["system"] = system

        response = await client.messages.create(**kwargs)
        # content mixes block types (thinking blocks come first); only text blocks carry the answer
        yield "".join(block.text for block in response.content if block.type == "text")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Anthropic doesn't have a native embeddings API
        # Raise to signal caller should use local embeddings
        raise NotImplementedError(
            "Anthropic does not support embeddings. Use the local EmbeddingService."
        )
