"""Abstract LLM adapter interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class LLMAdapter(ABC):
    """Abstract base for LLM provider adapters."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        stream: bool = False,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        """
        Generate a completion.

        When stream=True, yields tokens as they arrive.
        When stream=False, yields a single string with the full response.
        """
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier."""
        ...
