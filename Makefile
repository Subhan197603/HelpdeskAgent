SHELL := /bin/sh
.DEFAULT_GOAL := help

.PHONY: help bootstrap up down logs db-install db-demo db-reset migrate migration seed \
	api worker web lint format format-check typecheck test test-integration test-e2e \
	openapi clean compose-validate

help:
	@echo "Fusion AI Helpdesk development commands"
	@echo "  bootstrap        Install locked dependencies and create .env if missing"
	@echo "  up/down/logs     Manage local dependency containers"
	@echo "  lint/typecheck/test/format-check  Run quality gates"

bootstrap:
	@test -f .env || cp .env.example .env
	uv sync --frozen
	pnpm install --frozen-lockfile

up:
	docker compose up -d --wait postgres redis minio minio-init mailpit clamav

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

db-install:
	@test -f database/baseline/fusion_helpdesk_postgres/sql/install_all.sql || \
		(echo "PostgreSQL baseline is not present; complete Task 0.2 first." && exit 1)
	psql "$$DATABASE_ADMIN_URL" -f database/baseline/fusion_helpdesk_postgres/sql/install_all.sql

db-demo:
	@test -f database/baseline/fusion_helpdesk_postgres/sql/10_demo_bootstrap.sql || \
		(echo "PostgreSQL baseline is not present; complete Task 0.2 first." && exit 1)
	psql "$$DATABASE_ADMIN_URL" -f database/baseline/fusion_helpdesk_postgres/sql/10_demo_bootstrap.sql
	psql "$$DATABASE_ADMIN_URL" -f database/baseline/fusion_helpdesk_postgres/sql/11_demo_ticket.sql

db-reset:
	@echo "Database reset will be implemented with the baseline in Task 0.2."
	@exit 1

migrate migration seed:
	@echo "$@ will be implemented with the application database foundation."
	@exit 1

api worker web:
	@echo "$@ runtime will be implemented in its foundation task."
	@exit 1

lint:
	uv run ruff check .
	pnpm lint

format:
	uv run ruff format .
	pnpm format:write

format-check:
	uv run ruff format --check .
	pnpm format

typecheck:
	uv run mypy
	pnpm typecheck

test:
	uv run pytest
	pnpm test

test-integration:
	uv run pytest tests/integration -m integration

test-e2e:
	@echo "End-to-end tests begin with the web vertical slice."

openapi:
	@echo "OpenAPI generation begins with the FastAPI foundation."

compose-validate:
	docker compose config --quiet

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .venv node_modules coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
