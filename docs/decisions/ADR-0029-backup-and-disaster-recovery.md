# ADR-0029: Backup and disaster recovery baseline

## Status

Accepted (2026-08-03)

## Context

Milestone 10 Task 10.3 requires a validated recovery posture: backup
strategy, point-in-time recovery planning, object-storage and secrets
recovery, an actual restore test, and recovery-objective evidence. The
platform stores authoritative state in PostgreSQL (all schemas including
append-only audit history), attachment objects in MinIO/S3, and secrets in
the deployment secret store.

## Decision

- Logical backups are the portable recovery tier: `pg_dump --format=custom`
  produced and verified by `infrastructure/backup/backup_database.sh`, and
  restored by `infrastructure/backup/restore_database.sh` with
  `--exit-on-error` so partial restores fail loudly.
- Point-in-time recovery is a production-deployment concern layered on top:
  WAL archiving plus nightly base backups. The repository asserts the
  database prerequisites (`wal_level`, `full_page_writes`) rather than
  simulating archive infrastructure locally.
- The restore procedure is exercised, not merely documented: an integration
  drill (`tests/integration/test_backup_restore.py`) seeds data, backs up,
  writes past the backup point, destroys and restores the database, and
  asserts fingerprint equality, the recovery-point boundary, a restore-time
  ceiling, migration head, and surviving append-only enforcement.
- Object storage relies on bucket versioning plus mirrored replication;
  database rows remain the source of truth for attachment metadata and scan
  status.
- `.env.example` is the authoritative configuration inventory; secret values
  live only in the secret store with version history.
- Rollback strategy is application-level (previous images against an
  additive-first schema); schema downgrade is never the production recovery
  path — restore from backup is.

## Consequences

- Recovery is provable on every full validation run, with measured restore
  time as RTO evidence and the RPO boundary demonstrated by construction.
- Local environments carry a 24-hour logical-backup RPO; the 15-minute
  production RPO depends on enabling WAL archiving at deployment, recorded
  as an accepted risk in the production-readiness review.
- Restore scripts double as the documented manual procedure, so drift
  between automation and documentation is structurally impossible.
