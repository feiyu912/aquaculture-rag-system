.PHONY: install up down api worker pdf migrate test lint smoke eval

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

migrate:
	cd apps/api && uv run python ../../scripts/migrate_db.py

test:
	cd apps/api && uv run pytest -q

lint:
	cd apps/api && uv run ruff check app tests ../../scripts

smoke:
	cd apps/api && uv run python ../../scripts/smoke_test.py

eval:
	cd apps/api && uv run python ../../scripts/evaluate.py \
		--dataset ../../eval/sample_questions.jsonl \
		--modes dense,bm25,hybrid,hybrid_rerank \
		--out ../../eval/runs/demo