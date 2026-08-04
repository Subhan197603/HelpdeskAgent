# Operational Runbooks

Release-engineering and incident runbooks for the Fusion AI Helpdesk platform.
Alert-driven runbooks (error rate, latency, SLA worker lag, AI budget, pool
saturation, outbox backlog, provider failure rate) live in
[monitoring.md](monitoring.md); backup and restore mechanics live in
[backup-disaster-recovery.md](backup-disaster-recovery.md).

## Runbook: Deployment

### Trigger

A tagged release candidate has passed the full validation gate and is approved
for an environment.

### Steps

1. Confirm the working tree tag matches the approved release
   (`git describe --tags`).
2. Build and push images from the tag: `docker build` for
   `apps/api/Dockerfile` and `apps/web/Dockerfile`, tagged with the release
   version.
3. Apply database migrations before rolling application pods:
   `python -m apps.api.app.db.migrations_cli upgrade` (migrations are
   additive-first per policy, so old code runs against the new schema).
4. Roll out the API, workers, and web images.
5. Keep the previous image tags available for rollback.

### Verification

- `/api/v1/health` reports every dependency healthy.
- `python -m apps.api.app.db.migrations_cli check` reports the expected head.
- `/api/v1/observability/metrics` serves counters and dashboards resume.
- Smoke path: sign in, load the catalogue, open a queue.

## Runbook: Rollback

### Trigger

A deployment causes elevated error rate, failed health checks, or a functional
regression that cannot be fixed forward quickly.

### Steps

1. Redeploy the previous known-good image tags (API, workers, web).
2. Leave the database schema in place: migrations are additive-first, so the
   previous application version runs against the newer schema. Do not
   downgrade the schema as the immediate rollback action.
3. If a migration itself corrupted data, treat it as an incident and follow
   the restore procedure in
   [backup-disaster-recovery.md](backup-disaster-recovery.md) instead of an
   in-place downgrade.
4. Announce the rollback and freeze further deploys until the cause is known.

### Verification

- Health, metrics, and the smoke path pass on the rolled-back version.
- Error-rate and latency alerts clear.

## Runbook: Database migration

### Trigger

A release includes new Alembic revisions, or a migration failed mid-deploy.

### Steps

1. Before applying: confirm linear history and single head
   (`python -m apps.api.app.db.migrations_cli check` against a staging copy).
2. Take a fresh logical backup with
   `infrastructure/backup/backup_database.sh` so the pre-migration state is
   restorable.
3. Apply with `python -m apps.api.app.db.migrations_cli upgrade`.
4. On failure: the failed revision runs in a transaction and rolls back;
   fix forward if the cause is transient, otherwise restore the
   pre-migration backup with `infrastructure/backup/restore_database.sh`
   and redeploy the previous application version.
5. Downgrades (`downgrade`) are reserved for staging verification, not
   production recovery.

### Verification

- `migrations_cli check` reports the expected head.
- Integration smoke: ticket read and submit paths succeed.
- No destructive-migration guard warnings in the migration output.

## Runbook: Incident response

### Trigger

Any critical alert, user-reported outage, or data-integrity concern.

### Steps

1. Acknowledge the alert and open an incident channel; assign an incident
   lead.
2. Classify severity: availability, data integrity, security, or AI
   behaviour (security → [Security incident](#runbook-security-incident);
   AI behaviour → [AI disable](#runbook-ai-disable)).
3. Stabilise first: roll back the latest change ([Rollback](#runbook-rollback))
   or disable the failing subsystem before root-causing.
4. Capture evidence while mitigating: correlation IDs from structured logs,
   `/api/v1/observability/metrics` snapshots, relevant `audit.security_event`
   and `ai.agent_run` rows.
5. After mitigation, write a timeline and post-incident review with actions.

### Verification

- Alert has cleared and stayed clear for one full evaluation window.
- Post-incident review recorded with owners for follow-up actions.

## Runbook: Security incident

### Trigger

Suspected credential leak, cross-tenant access, injection attempt, or a
critical vulnerability report; `audit.security_event` anomalies.

### Steps

1. Engage the security owner; treat as confidential.
2. Contain: revoke the affected credentials (OIDC client secrets, database
   passwords, `OPENAI_API_KEY`, object-storage keys) and rotate via the
   secret store; sessions bound to revoked credentials terminate on next
   token validation.
3. Preserve evidence: export relevant `audit.security_event`,
   `audit.audit_event`, and `ai.tool_call` rows — these tables are
   append-only, so history is trustworthy.
4. Assess blast radius with tenant-scoped queries; confirm RLS and grants
   with the security regression suite
   (`tests/integration/test_security_regression.py`).
5. Remediate the vulnerability, add a regression test, and record the finding
   in [../security/security-test-plan.md](../security/security-test-plan.md)'s
   findings register.

### Verification

- Rotated credentials verified working; old credentials verified rejected
  (401 with a `DENIED` security event).
- Security regression suite passes.
- Finding recorded with owner and status in the findings register.

## Runbook: AI disable

### Trigger

AI answers exhibiting unsafe behaviour, runaway spend, hallucinated citations
in production, or a directive to suspend AI features.

### Steps

1. Fast path (environment): set `AI_GLOBALLY_ENABLED=false` and restart the
   API. Every gateway call then fails closed with `ai_disabled` before any
   provider traffic.
2. Scoped path (database): disable the relevant AI policy row so a single
   agent or use case is suspended while others continue.
3. Confirm no autonomous behaviour continues: the platform performs no
   AI-initiated state changes, so disabling generation halts all AI activity.
4. Communicate the degraded mode: employee agent and analyst copilot return
   the safe AI-unavailable state; human workflows continue unaffected.
5. Re-enable only after the root cause is understood and, where relevant, the
   evaluation thresholds in `tests/ai_evaluation/` pass.

### Verification

- AI endpoints return the safe unavailable/disabled state, not errors.
- `ai.usage_ledger` shows no new provider spend after the disable timestamp.
- Ticket submission, queues, and knowledge browsing operate normally.

## Runbook: AI provider outage

### Trigger

`AIProviderFailureRate` alert, provider status-page incident, or sustained
timeouts from the model provider.

### Steps

1. Confirm the failure is upstream: provider error rate in metrics
   (`helpdesk_copilot_provider_failures_total`) rising while non-AI endpoints
   stay healthy.
2. No action is required to protect users: the circuit breaker
   (`AI_CIRCUIT_FAILURE_THRESHOLD` / `AI_CIRCUIT_RECOVERY_SECONDS`) opens and
   AI surfaces return the safe unavailable state; budgets are not consumed by
   failed calls.
3. If the outage is prolonged, set `AI_GLOBALLY_ENABLED=false`
   ([AI disable](#runbook-ai-disable)) to stop retry pressure and present a
   consistent degraded mode.
4. If an alternative provider alias is configured and approved, switch the
   model policy to it; version capture on `ai.agent_run` records the change.
5. Re-enable after the provider recovers; the circuit breaker closes after
   successful probes.

### Verification

- Provider failure counters stop increasing; copilot and employee-agent
  requests succeed end to end.
- A spot-check `ai.agent_run` row records the expected model and versions.
- No unsafe partial answers were served during the outage (AI responses were
  the explicit unavailable state).
