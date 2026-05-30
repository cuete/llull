# ============================================================
# Llull Service — Multi-stage Dockerfile
# ============================================================

# --- Builder stage ---
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

COPY pyproject.toml ./

# Install dependencies into .venv
RUN uv venv /app/.venv && \
    uv pip install --python /app/.venv/bin/python \
    fastapi uvicorn[standard] pydantic pydantic-settings \
    sqlalchemy aiosqlite httpx tenacity structlog python-multipart \
    sse-starlette tiktoken sentence-transformers \
    pymupdf python-docx openpyxl beautifulsoup4 pytesseract Pillow \
    azure-storage-blob anthropic openai PyJWT cryptography

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR support
    tesseract-ocr \
    tesseract-ocr-eng \
    # Pandoc for export
    pandoc \
    # Required for sqlite extensions
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Set PATH to use venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Copy application code
COPY app/ ./app/

# Create data directory
RUN mkdir -p /app/data/uploads

# Non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
