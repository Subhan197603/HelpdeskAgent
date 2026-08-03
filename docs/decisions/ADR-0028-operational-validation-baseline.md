# ADR-0028: Deterministic performance, security, and AI evaluation baseline

- Status: Accepted
- Date: 2026-08-03

## Context

Task 10.2 requires load and concurrency validation, a security test plan with penetration
coverage, AI quality thresholds, and monitoring with actionable alerts — all runnable by any
engineer and by CI without external load-testing or observability SaaS dependencies.

## Decision

Validation is expressed as deterministic test suites and versioned configuration rather than
one-off exercises:

- **Performance** (`tests/performance/test_api_performance.py`) runs against real PostgreSQL:
  concurrent API load with a p95 latency budget, concurrent ticket submissions proving
  uniqueness and idempotent replay under a duplicate-key storm, queue pagination over a seeded
  300-ticket backlog, and pool-sizing verification that a deliberately small pool sustains a
  burst beyond its capacity and returns to zero checked-out connections. Retrieval latency
  thresholds remain enforced by the Task 7.3 regression corpus.
- **Security** — `docs/security/security-test-plan.md` is the plan of record; penetration cases
  are deterministic tests in `tests/integration/test_security_regression.py` (cross-tenant
  enumeration, direct-object reference, cross-tenant writes, privilege escalation,
  authentication bypass, plus a positive control). The findings register tracks acceptance of
  the two known non-high findings; critical/high findings block release.
- **AI evaluation** (`tests/ai_evaluation/test_agent_thresholds.py`) drives the real
  employee-agent answer path and copilot claim binding through fakes over a fixed corpus and
  enforces hard thresholds: 100% citation coverage on proposed resolutions, 100% safe
  escalation/refusal for unsupported questions, and a 0% fabricated-citation rate.
- **Monitoring** — the API exposes Prometheus text-format counters at
  `/api/v1/observability/metrics` (toggle `METRICS_ENDPOINT_ENABLED`); alert rules live in
  `infrastructure/monitoring/prometheus-alerts.yml`; SLOs, dashboards, and per-alert runbooks
  live in `docs/operations/monitoring.md`. A policy test asserts every alert carries a severity
  and a resolvable runbook link, and that the critical set covers error rate, AI budget, and
  pool saturation.

## Consequences

- Latency budgets and AI thresholds are code: regressions fail CI instead of surfacing in
  production.
- Alert rules cannot drift from their runbooks — the policy test binds them.
- The metrics endpoint exposes only aggregate counters, no tenant or personal data, and can be
  disabled per environment.
- External load tests and third-party penetration assessments remain deployment-time exercises
  (Task 10.3 readiness), layered on top of this deterministic baseline.
