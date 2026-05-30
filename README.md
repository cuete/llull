# Llull

A document analysis workspace — NotebookLM-style with a semantic analysis methodology based on iterative zooms into a knowledge graph.

## What It Is

Llull is a backend service that lets you:
- Ingest documents (PDF, DOCX, XLSX, text, URL, image)
- Build a semantic knowledge graph from the content
- Explore the graph iteratively with "zoom" operations that drill into concepts
- Chat with your documents using RAG + graph context
- Export findings to PDF, Markdown, HTML, or ZIP

## Architecture

- **Python 3.11+ / FastAPI** — async REST API + SSE streaming
- **SQLite + sqlite-vec** — document store + vector embeddings
- **Azure Blob Storage** — source file storage (optional in local dev)
- **sentence-transformers** (all-mpnet-base-v2) — local embeddings
- **LLM adapter pattern** — OpenAI / Anthropic / Ollama, configurable
- **Docker + docker-compose** — local dev environment

## Quick Start

```bash
cd service
cp .env.example .env
# Edit .env — set LLM_PROVIDER, LLM_API_KEY, etc.
docker compose up --build
```

API available at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

## Local Dev (without Docker)

```bash
cd service
pip install uv
uv sync
cp .env.example .env
# Edit .env
make dev
```

## Testing

```bash
cd service
make test
```

## Configuration

See `.env.example` for all environment variables.

Key settings:
- `AUTH_ENABLED=false` — disable auth for local dev (uses hardcoded test user)
- `LLM_PROVIDER` — `openai`, `anthropic`, or `ollama`
- `STORAGE_BACKEND` — `azure` or `local`

## API Documentation

- OpenAPI (Swagger): `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Deployment

See `service/docs/azure-deployment.md` for full Azure deployment guide.

## License

MIT License — see [LICENSE](LICENSE)
