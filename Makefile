SHELL := /bin/sh
.DEFAULT_GOAL := help

.PHONY: help bootstrap up down logs db-install db-demo db-reset migrate migration seed \
	api worker web lint format format-check typecheck test test-integration test-e2e \
	openapi clean compose-validate db-demo-bootstrap db-demo-ticket db-test

COMPOSE ?= docker compose
DB_SERVICE ?= postgres
DB_NAME ?= helpdesk
APP_ENV ?= development

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
	$(COMPOSE) up -d --wait postgres redis minio minio-init mailpit clamav

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

db-install:
	@test -f database/baseline/fusion_helpdesk_postgres/sql/install_all.sql || \
		(echo "PostgreSQL baseline is not present; complete Task 0.2 first." && exit 1)
	$(COMPOSE) up -d --wait $(DB_SERVICE)
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 -U postgres -d $(DB_NAME) \
		-f /baseline/install_all.sql

db-demo: db-demo-bootstrap db-demo-ticket

db-demo-bootstrap:
	@test -f database/baseline/fusion_helpdesk_postgres/sql/10_demo_bootstrap.sql || \
		(echo "PostgreSQL baseline is not present; complete Task 0.2 first." && exit 1)
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 -U postgres -d $(DB_NAME) \
		-f /baseline/10_demo_bootstrap.sql

db-demo-ticket:
	@test -f database/baseline/fusion_helpdesk_postgres/sql/11_demo_ticket.sql || \
		(echo "PostgreSQL baseline is not present; complete Task 0.2 first." && exit 1)
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 -U postgres -d $(DB_NAME) \
		-f /baseline/11_demo_ticket.sql

db-reset:
	@test "$(APP_ENV)" = "development" || \
		(echo "Refusing reset: APP_ENV must be development." && exit 1)
	@test "$(CONFIRM_DB_RESET)" = "local-helpdesk" || \
		(echo "Refusing reset: pass CONFIRM_DB_RESET=local-helpdesk." && exit 1)
	$(COMPOSE) up -d --wait $(DB_SERVICE)
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
		-c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'helpdesk' AND pid <> pg_backend_pid();"
	$(COMPOSE) exec -T $(DB_SERVICE) dropdb --if-exists -U postgres helpdesk
	$(COMPOSE) exec -T $(DB_SERVICE) createdb -U postgres helpdesk
	$(MAKE) db-install DB_NAME=helpdesk

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
	uv run pytest -m "not integration"
	pnpm test

test-integration:
	uv run pytest tests/integration -m integration

db-test: test-integration

test-e2e:
	@echo "End-to-end tests begin with the web vertical slice."

openapi:
	@echo "OpenAPI generation begins with the FastAPI foundation."

compose-validate:
	$(COMPOSE) config --quiet

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .venv node_modules coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
