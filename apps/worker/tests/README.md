# Worker tests

Worker settings safety is covered locally, while SLA domain and calendar unit coverage is under
`apps/api/tests/test_sla.py`. Worker claiming,
non-owner/RLS behavior, retry-safe reprocessing, and lifecycle persistence are covered against
PostgreSQL by `tests/integration/test_sla_engine.py`.
