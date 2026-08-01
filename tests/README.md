# Cross-cutting tests

- `integration/` contains tests requiring real infrastructure.
- `end_to_end/` contains Playwright workflows.
- `performance/` contains load and latency tests.
- `ai_evaluation/` contains versioned AI evaluation datasets and runners.

Active integration coverage uses isolated Docker Compose projects for the physical PostgreSQL
baseline, Alembic adoption and locking, Redis health, and the FastAPI container.
