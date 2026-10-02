# syntax=docker/dockerfile:1

# ---- Frontend build ----
FROM node:20-slim AS frontend-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Same origin as the API in production — no cross-origin base URL needed.
ARG VITE_MSAL_CLIENT_ID=""
ENV VITE_API_BASE_URL=""
ENV VITE_MSAL_CLIENT_ID=${VITE_MSAL_CLIENT_ID}
RUN npm run build

# ---- Backend ----
FROM python:3.11-slim AS backend
WORKDIR /app

# tesseract-ocr: required at runtime by pytesseract (image source parsing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY service/pyproject.toml service/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the embedding model into the image: the app scales to zero, and without this
# every cold start would re-download it from Hugging Face. Must match EMBEDDING_MODEL.
ARG EMBEDDING_MODEL=all-mpnet-base-v2
ENV HF_HOME=/app/.cache/huggingface
RUN /app/.venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}')"

COPY service/app ./app

# Built frontend, served by the FastAPI app itself (see app.config.static_dir)
COPY --from=frontend-build /web/dist ./web-dist

ENV STATIC_DIR=/app/web-dist
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
