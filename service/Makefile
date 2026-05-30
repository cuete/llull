.PHONY: dev test lint clean install docker-up docker-down

install:
	pip install uv && uv sync --all-extras

dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	uv run pytest tests/ -v

test-cov:
	uv run pytest tests/ -v --cov=app --cov-report=html --cov-report=term-missing

lint:
	uv run ruff check app/ tests/
	uv run ruff format --check app/ tests/

format:
	uv run ruff format app/ tests/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov .ruff_cache

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v
