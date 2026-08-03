# Monitoring, SLOs, and alerting

Task 10.2 defines the observability baseline: structured logs, Prometheus-compatible metrics,
trace propagation, alert rules with runbook links, and the AI evaluation thresholds enforced in
CI.

## Telemetry

- **Logs** — structured application logging with `correlation_id` and `request_id` on every API
  request (`apps/api/app/core/middleware.py`). Log level and JSON output via `LOG_LEVEL` /
  `JSON_LOGS`. No tokens, prompts, document bodies, or personal data are logged.
- **Metrics** — `GET /api/v1/observability/metrics` serves Prometheus text format from in-process
  service counters (tickets, catalogue, analyst copilot, AI provider failures, feedback
  decisions). Toggle with `METRICS_ENDPOINT_ENABLED`; expose only on the internal network.
  Infrastructure metrics referenced by alerts (`http_requests_total`, pool gauges, worker
  timestamps) come from the platform exporters configured in deployment.
- **Traces** — outbound OTLP endpoint via `OTEL_EXPORTER_OTLP_ENDPOINT`; correlation ids join
  logs to traces.

## Service level objectives

| SLO                            | Target                                     | Measured by                                      |
| ------------------------------ | ------------------------------------------ | ------------------------------------------------ |
| API availability               | 99.5% monthly                              | 1 − (5xx / total requests)                       |
| API latency                    | p95 ≤ 500 ms                               | `http_request_duration_seconds`                  |
| Ticket submission durability   | 100% idempotent (no duplicates)            | concurrency tests + idempotency conflicts metric |
| SLA worker freshness           | cycle lag < 120 s                          | worker heartbeat timestamp                       |
| AI citation coverage           | 100% of proposed resolutions cite evidence | `tests/ai_evaluation/test_agent_thresholds.py`   |
| AI unsupported-answer handling | 100% escalate/refuse safely                | same suite                                       |
| AI hallucinated citation rate  | 0%                                         | same suite + copilot claim binding               |

AI thresholds run in CI as the AI evaluation suite; a regression fails the build.

## Alert rules

Rules live in `infrastructure/monitoring/prometheus-alerts.yml` and are policy-checked by
`apps/api/tests/test_monitoring_configuration.py` (every alert must carry a severity and a
runbook link; the critical set must include error-rate, AI-budget, and pool-saturation alerts).

| Alert                 | Severity | Runbook                                       |
| --------------------- | -------- | --------------------------------------------- |
| APIHighErrorRate      | critical | [API high error rate](#api-high-error-rate)   |
| APIHighLatencyP95     | warning  | [API high latency](#api-high-latency)         |
| DBPoolSaturation      | critical | [DB pool saturation](#db-pool-saturation)     |
| SLAWorkerLag          | warning  | [SLA worker lag](#sla-worker-lag)             |
| OutboxBacklog         | warning  | [Outbox backlog](#outbox-backlog)             |
| AIProviderFailureRate | warning  | [AI provider failures](#ai-provider-failures) |
| AIBudgetNearHardStop  | critical | [AI budget hard stop](#ai-budget-hard-stop)   |

## Dashboards

Operational dashboards (Grafana or OAC operational workbook) mirror the reporting dashboard
specifications in `docs/operations/reporting-oac.md` plus an engineering dashboard: request
rate/error rate/latency, DB pool usage, outbox depth, SLA worker heartbeat, AI usage and failure
counters from the metrics endpoint.

## Runbook: api high error rate

1. Check recent deploys; roll back if the spike aligns with a release.
2. Inspect structured logs filtered by `status>=500`, group by `correlation_id`.
3. Verify PostgreSQL, Redis, object storage, ClamAV health via `/api/v1/health/readiness`.
4. If a single endpoint is failing, disable the owning feature flag where available.

## Runbook: api high latency

1. Compare latency against DB pool saturation and PostgreSQL slow queries.
2. Check queue/retrieval endpoints first — they carry the heaviest queries.
3. Scale API replicas or raise pool limits only after confirming the DB is healthy.

## Runbook: db pool saturation

1. Inspect `helpdesk_db_pool_*` gauges; identify the leaking or slow workload.
2. Check for long-running transactions in `pg_stat_activity`.
3. Restart the offending deployment if connections are leaked; review recent changes to
   session/transaction handling.

## Runbook: sla worker lag

1. Check worker container health and logs.
2. Verify outbox consumption is progressing; look for poison messages.
3. Restart the worker; SLA jobs are idempotent and recalculate deterministically.

## Runbook: outbox backlog

1. Identify the failing event types in `integration.outbox_event` with status FAILED/PENDING.
2. Check downstream dependencies (SMTP, notification channels).
3. Re-run the worker consumers; events are idempotent via deduplication keys.

## Runbook: ai provider failures

1. Check provider status pages and the circuit-breaker state.
2. Confirm ticketing continues on the deterministic path (it must; AI is optional).
3. If sustained, disable AI via the runtime kill switch; no user-facing outage should result.

## Runbook: ai budget hard stop

1. Review `reporting.fact_ai_usage` spend by provider/model/use case.
2. Raise the approved budget or leave the hard stop in place; the application degrades safely.
3. Investigate anomalous usage (runaway retries, unexpectedly large contexts) before raising.
