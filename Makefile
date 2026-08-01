SHELL := /bin/sh
.DEFAULT_GOAL := help

.PHONY: help bootstrap up down logs db-install db-runtime-role db-demo db-reset migrate migration migration-check migration-current migration-history db-stamp-baseline db-validate-baseline seed db-seed-identities \
	api worker web lint format format-check typecheck test test-integration test-e2e \
	openapi clean compose-validate db-demo-bootstrap db-demo-ticket db-test db-seed-catalogue

COMPOSE ?= docker compose
DB_SERVICE ?= postgres
DB_NAME ?= helpdesk
APP_ENV ?= development
API_HOST ?= 127.0.0.1
API_PORT ?= 8000
API_RELOAD ?= false
POSTGRES_APP_PASSWORD ?= helpdesk
MIGRATOR := $(COMPOSE) --profile tools run --rm migrator

help:
	@echo "Fusion AI Helpdesk development commands"
	@echo "  bootstrap        Install locked dependencies and create .env if missing"
	@echo "  up/down/logs     Manage local dependency containers"
	@echo "  db-validate-baseline/db-stamp-baseline  Adopt the physical baseline"
	@echo "  migrate/migration/migration-check       Manage reviewed Alembic changes"
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
	$(MAKE) db-runtime-role DB_NAME=$(DB_NAME)

db-runtime-role:
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 \
		-v app_password="$(POSTGRES_APP_PASSWORD)" -U postgres -d $(DB_NAME) \
		-f /runtime-config/configure_local_runtime.sql

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

migrate:
	$(MIGRATOR) python -m apps.api.app.db.migrations_cli upgrade head

migration:
	@test -n "$(MIGRATION_ID)" || (echo "MIGRATION_ID is required (for example 0002_identity_subject_index)." && exit 1)
	@test -n "$(MIGRATION_MESSAGE)" || (echo "MIGRATION_MESSAGE is required." && exit 1)
	uv run alembic -c apps/api/alembic.ini revision --rev-id "$(MIGRATION_ID)" -m "$(MIGRATION_MESSAGE)"

migration-check:
	uv run python -m apps.api.app.db.migrations_cli check

migration-current:
	$(MIGRATOR) python -m apps.api.app.db.migrations_cli current

migration-history:
	$(MIGRATOR) python -m apps.api.app.db.migrations_cli history

db-validate-baseline:
	$(MIGRATOR) python -m apps.api.app.db.migrations_cli validate

db-stamp-baseline:
	$(MIGRATOR) python -m apps.api.app.db.migrations_cli stamp

seed: db-seed-identities db-seed-catalogue

db-seed-identities:
	@test "$(APP_ENV)" = "development" || \
		(echo "Refusing developer identity seed: APP_ENV must be development." && exit 1)
	$(COMPOSE) up -d --wait $(DB_SERVICE)
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 -U postgres -d $(DB_NAME) \
		-f /development/identity_personas.sql

db-seed-catalogue:
	@test "$(APP_ENV)" = "development" || \
		(echo "Refusing catalogue seed: APP_ENV must be development." && exit 1)
	$(COMPOSE) up -d --wait $(DB_SERVICE)
	$(COMPOSE) exec -T $(DB_SERVICE) psql -v ON_ERROR_STOP=1 -U postgres -d $(DB_NAME) \
		-f /development/catalogue.sql

api:
	uv run uvicorn apps.api.app.main:app --host $(API_HOST) --port $(API_PORT) $(if $(filter true,$(API_RELOAD)),--reload,)

worker web:
	@echo "$@ runtime will be implemented in its foundation task."
	@exit 1

lint:
	uv run ruff check .
	uv run python -m apps.api.app.db.migrations_cli check
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
	uv run python -m apps.api.app.openapi

compose-validate:
	$(COMPOSE) config --quiet

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache .venv node_modules coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
