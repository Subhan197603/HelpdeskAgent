# Worker

The worker consumes tenant-scoped SLA input events from the PostgreSQL transactional outbox and
runs periodic warning/breach scans. It uses the non-owner `helpdesk_worker` database role through
`WORKER_DATABASE_URL` and applies transaction-local tenant context before touching ticket SLA
rows.

Run locally with:

```powershell
uv run python -m apps.worker.worker.main
```

Retries are idempotent: input rows are claimed with `FOR UPDATE SKIP LOCKED`, lifecycle events use
stable keys, and warning/breach events have database uniqueness protection. Failures retain only a
sanitized exception class in the outbox record and move to dead-letter after the configured
attempt limit.
