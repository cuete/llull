"""Embedding service using sentence-transformers."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# EMBEDDING_DIM for all-mpnet-base-v2
EMBEDDING_DIM = 768


class EmbeddingService:
    """Local embedding service using sentence-transformers."""

    def __init__(self, model_name: str = "all-mpnet-base-v2") -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _get_model(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_name)
                log.info("embedding_model_loaded", model=self._model_name)
            except ImportError as e:
                raise ImportError("sentence-transformers is required for embeddings") from e
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts."""
        if not texts:
            return []

        # Run in thread to avoid blocking the event loop
        import asyncio

        model = self._get_model()
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: model.encode(texts, convert_to_numpy=True).tolist()
        )
        log.info("embeddings_generated", count=len(texts), model=self._model_name)
        return embeddings

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        results = await self.embed([text])
        return results[0]

    def serialize(self, embedding: list[float]) -> str:
        """Serialize embedding to JSON string for storage."""
        return json.dumps(embedding)

    def deserialize(self, embedding_json: str) -> list[float]:
        """Deserialize embedding from JSON string."""
        return json.loads(embedding_json)

    def cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two embeddings."""
        import math

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
