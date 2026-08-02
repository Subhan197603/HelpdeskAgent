# Cross-cutting tests

- `integration/` contains tests requiring real infrastructure.
- `end_to_end/` contains Playwright workflows.
- `performance/` contains load and latency tests.
- `ai_evaluation/` contains versioned AI evaluation datasets and runners.

Active integration coverage uses isolated Docker Compose projects for the physical PostgreSQL
baseline, Alembic adoption and locking, Redis health, and the FastAPI container.

`ai_evaluation/retrieval_regression_v1.json` is the deterministic Milestone 7 retrieval corpus.
Its integration runner enforces employee/analyst and tenant boundaries, restricted-source denial,
release-family separation, exact identifier ranking, evidence integrity, zero-result behavior,
top-1/MRR quality thresholds, and a warm p95 latency ceiling. CI runs that gate explicitly in the
`retrieval-regression` job as well as through the repository integration suite.
