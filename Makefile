.PHONY: install up down api worker pdf test lint

install:
	cd apps/api && uv sync

up:
	docker compose -f infra/docker-compose.yml up -d

down:
	docker compose -f infra/docker-compose.yml down

api:
	cd apps/api && uv run uvicorn app.main:app --reload --port 8000

worker:
	cd apps/api && uv run arq app.worker.WorkerSettings

pdf:
	cd apps/api && uv run python ../../scripts/make_sample_pdf.py

test:
	cd apps/api && uv run pytest -q

lint:
	cd apps/api && uv run ruff check app tests ../../scripts