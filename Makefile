.PHONY: setup chat batch eval ingest test up down test-integration lint api openapi web gen-types

setup:
	uv sync

chat:
	uv run ircb chat

batch:
	uv run ircb batch $(IN) --out $(OUT)

eval:
	uv run ircb eval

ingest:
	uv run ircb ingest $(PDF)

test:
	uv run pytest

up:
	docker compose up -d --build --wait

down:
	docker compose down

# Equivalent without make (PowerShell: set $env:QDRANT_URL / $env:DATABASE_URL first):
#   docker compose up -d --wait
#   QDRANT_URL=http://localhost:6333 DATABASE_URL=postgresql+psycopg://ircb:ircb@localhost:5432/ircb #     uv run pytest -m integration
# The tests skip (never hang) when Qdrant / PostgreSQL are unreachable.
test-integration: up
	QDRANT_URL=http://localhost:6333 DATABASE_URL=postgresql+psycopg://ircb:ircb@localhost:5432/ircb uv run pytest -m integration

lint:
	uv run ruff check .
	uv run mypy
	uv run lint-imports

api:
	uv run uvicorn ircb_api.main:app --reload

openapi:
	uv run python -m ircb_api.openapi apps/web/openapi.json

web:
	pnpm --dir apps/web dev

gen-types: openapi
	pnpm --dir apps/web gen:types
