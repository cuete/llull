"""Source ingestion service."""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Chunk, Source
from app.models.task import Task
from app.parsers import get_parser
from app.services.embeddings import EmbeddingService
from app.services.prompt import count_tokens
from app.services.rating import RatingService
from app.services.sections import ensure_sections

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

# Chunking parameters
CHUNK_TOKEN_SIZE = 500
CHUNK_TOKEN_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = CHUNK_TOKEN_SIZE, overlap: int = CHUNK_TOKEN_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks of roughly chunk_size tokens.
    Uses simple sentence-aware splitting.
    """
    if not text.strip():
        return []

    # Split into sentences roughly
    sentences = text.replace("\n\n", "\n").split("\n")
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)
        if current_tokens + sentence_tokens > chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            # Overlap: keep last few sentences
            overlap_sentences: list[str] = []
            overlap_tokens = 0
            for s in reversed(current_chunk):
                t = count_tokens(s)
                if overlap_tokens + t > overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_tokens += t
            current_chunk = overlap_sentences
            current_tokens = overlap_tokens

        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


class IngestService:
    """Handles source ingestion: parsing, chunking, embedding."""

    def __init__(
        self,
        db: AsyncSession,
        embedding_service: EmbeddingService,
        storage_backend: str = "local",
        local_storage_path: str = "./data/uploads",
        azure_connection_string: str = "",
        azure_container: str = "",
        llm=None,
    ) -> None:
        self._db = db
        self._embeddings = embedding_service
        self._storage_backend = storage_backend
        self._local_storage_path = Path(local_storage_path)
        self._azure_connection_string = azure_connection_string
        self._azure_container = azure_container
        self._llm = llm

    async def ingest_file(
        self,
        topic_id: str,
        source_type: str,
        name: str,
        file_path: Path,
        task: Task,
    ) -> Source:
        """Ingest a file source."""
        return await self._ingest(topic_id, source_type, name, file_path, task)

    async def ingest_url(
        self,
        topic_id: str,
        name: str,
        url: str,
        task: Task,
    ) -> Source:
        """Ingest a URL source."""
        return await self._ingest(topic_id, "url", name, url, task)

    async def ingest_text(
        self,
        topic_id: str,
        name: str,
        content: str,
        task: Task,
    ) -> Source:
        """Ingest raw text."""
        return await self._ingest(topic_id, "text", name, content, task)

    async def _update_task_progress(self, task: Task, step: str, pct: int) -> None:
        task.progress = pct
        task.status = "running"
        await self._db.flush()
        log.info("task_progress", task_id=task.id, step=step, pct=pct)

    async def _ingest(
        self,
        topic_id: str,
        source_type: str,
        name: str,
        source_input: Path | str,
        task: Task,
    ) -> Source:
        """Core ingestion pipeline."""
        await self._update_task_progress(task, "parsing", 10)

        # 1. Parse
        parser = get_parser(source_type)
        extracted_text = await parser.extract(source_input)
        await self._update_task_progress(task, "extracted", 30)

        # 2. Optional: upload to blob storage
        blob_url: str | None = None
        if self._storage_backend == "azure" and isinstance(source_input, Path):
            try:
                blob_url = await self._upload_to_blob(source_input, name)
            except Exception as e:
                log.error("blob_upload_failed", name=name, error=str(e))
                raise  # Atomic: don't persist if blob upload fails
        elif self._storage_backend == "local" and isinstance(source_input, Path):
            blob_url = str(source_input)

        await self._update_task_progress(task, "uploading", 50)

        # 3. Persist Source
        # Store the original URL for URL-type sources so it can be surfaced in the UI
        source_url = str(source_input) if source_type == "url" else None

        source = Source(
            id=str(uuid.uuid4()),
            topic_id=topic_id,
            type=source_type,
            name=name,
            blob_url=blob_url,
            source_url=source_url,
            extracted_text=extracted_text,
        )
        self._db.add(source)
        await self._db.flush()

        await self._update_task_progress(task, "chunking", 60)

        # 4. Chunk
        text_chunks = chunk_text(extracted_text)
        chunks: list[Chunk] = []
        for i, chunk_text_val in enumerate(text_chunks):
            chunk = Chunk(
                id=str(uuid.uuid4()),
                source_id=source.id,
                topic_id=topic_id,
                text=chunk_text_val,
                order=i,
            )
            self._db.add(chunk)
            chunks.append(chunk)

        await self._db.flush()
        await self._update_task_progress(task, "embedding", 75)

        # 5. Generate embeddings (degraded mode if this fails)
        try:
            if chunks:
                chunk_texts = [c.text for c in chunks]
                embeddings = await self._embeddings.embed(chunk_texts)
                for chunk, emb in zip(chunks, embeddings):
                    chunk.embedding_json = self._embeddings.serialize(emb)
                await self._db.flush()
        except Exception as e:
            log.warning("embedding_generation_failed", source_id=source.id, error=str(e))
            # Continue in degraded mode — source usable without embeddings

        # 5b. Group chunks into sections (chapters/headings) for layered analysis
        await ensure_sections(self._db, source)

        # 6. Rate the source (AI suspicion + quality score)
        if self._llm is not None:
            try:
                rating_svc = RatingService(self._llm)
                ratings = await rating_svc.rate_source(extracted_text)
                source.ai_suspicion = ratings.get("ai_suspicion")
                source.ai_suspicion_reason = ratings.get("ai_suspicion_reason")
                source.quality_score = ratings.get("quality_score")
                source.quality_reason = ratings.get("quality_reason")
                await self._db.flush()
                log.info(
                    "rating_complete",
                    source_id=source.id,
                    ai_suspicion=source.ai_suspicion,
                    quality_score=source.quality_score,
                )
            except Exception as e:
                log.warning("rating_skipped", source_id=source.id, error=str(e))

        # 7. Mark task done
        task.status = "done"
        task.progress = 100
        task.result = json.dumps({"source_id": source.id})
        await self._db.flush()

        log.info("ingest_complete", source_id=source.id, chunks=len(chunks))
        return source

    async def _upload_to_blob(self, file_path: Path, name: str) -> str:
        """Upload file to Azure Blob Storage. Returns blob URL."""
        try:
            from azure.storage.blob.aio import BlobServiceClient
        except ImportError as e:
            raise ImportError("azure-storage-blob is required for Azure storage") from e

        blob_name = f"{uuid.uuid4()}/{name}"
        async with BlobServiceClient.from_connection_string(
            self._azure_connection_string
        ) as client:
            container_client = client.get_container_client(self._azure_container)
            async with container_client.get_blob_client(blob_name) as blob_client:
                with file_path.open("rb") as f:
                    await blob_client.upload_blob(f, overwrite=True)
                return blob_client.url
