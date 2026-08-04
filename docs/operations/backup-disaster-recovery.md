# Backup and Disaster Recovery

This document defines the backup strategy, recovery procedures, and disaster
recovery evidence for the Fusion AI Helpdesk platform. The automated restore
test in `tests/integration/test_backup_restore.py` executes the procedures
below on every full validation run.

## Backup strategy

| Asset                                          | Mechanism                                                                                                           | Frequency                                              | Retention            |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ | -------------------- |
| PostgreSQL (all schemas)                       | `pg_dump --format=custom` via `infrastructure/backup/backup_database.sh`, archive verified with `pg_restore --list` | Nightly full; WAL archiving continuously in production | 30 daily, 12 monthly |
| WAL archive (production)                       | `archive_command` shipping to object storage                                                                        | Continuous                                             | 30 days              |
| Object storage (attachments bucket `helpdesk`) | Bucket versioning plus scheduled `mc mirror` replication to a secondary bucket/region                               | Continuous (versioning) + nightly mirror               | 30 days of versions  |
| Secrets and configuration                      | Sealed secret store (production) plus `.env.example` as the authoritative variable inventory                        | On change                                              | Full history         |
| Container images                               | Tagged immutable images (`fusion-ai-helpdesk-api`, `fusion-ai-helpdesk-web`) in the registry                        | Per release                                            | All release tags     |

Backups are executed by the `postgres` superuser against the primary database.
Every archive is verified readable (`pg_restore --list`) before the backup job
reports success; an unverifiable archive fails the job.

## Point-in-time recovery

Production PostgreSQL runs with the prerequisites PITR requires, and the
automated test asserts them:

- `wal_level` must be `replica` or `logical` (never `minimal`).
- `full_page_writes` must be `on`.

Production plan: enable `archive_mode = on` with an `archive_command` that
ships WAL segments to versioned object storage. Recovery to a point in time
uses a nightly base backup (`pg_basebackup`) plus replayed WAL with
`recovery_target_time`. Local/dev environments use logical backups only; the
recovery point there is the last completed logical backup, which the restore
test proves by demonstrating that post-backup writes do not survive a restore.

## Object storage protection and recovery

- The MinIO/S3 bucket holding attachment objects is created with versioning
  enabled so object overwrite or deletion is recoverable.
- A nightly `mc mirror --overwrite` job replicates the bucket to a secondary
  target; production S3 uses cross-region replication instead.
- Recovery: re-point `OBJECT_STORAGE_*` settings at the replica (or restore
  versions in place with `mc undo`/S3 version restore). Attachment metadata
  lives in PostgreSQL; the storage key is the join point, so database and
  bucket restores are independent.
- Malware-scan state is preserved in the database; restored objects are not
  re-served until their `scan_status` remains `CLEAN`.

## Secrets and configuration recovery

- `.env.example` is the complete, authoritative inventory of runtime
  configuration variables; every deployable setting appears there with a safe
  placeholder. Reconstructing an environment starts from this file.
- Production secret values (database passwords, `OPENAI_API_KEY`,
  `OBJECT_STORAGE_SECRET_KEY`, OIDC client secrets) live only in the
  deployment secret store, which retains version history for rollback.
- Database roles and grants are part of the schema baseline and migrations, so
  a database restore reinstates the full authorization model without manual
  grant reconstruction — the restore test verifies append-only enforcement
  survives restore.

## Restore procedure

1. Stop application writers (scale API and workers to zero).
2. Copy the chosen archive to a host with `pg_restore` access.
3. Run `infrastructure/backup/restore_database.sh` with `RESTORE_DATABASE` and
   `BACKUP_PATH` set. The script terminates residual connections, recreates
   the database, and restores with `--exit-on-error` so partial restores fail
   loudly.
4. Run `python -m apps.api.app.db.migrations_cli check` to confirm the
   restored database is at the expected migration head.
5. If restoring to a point in time (production), restore the base backup,
   configure `recovery_target_time`, and let WAL replay complete before
   accepting connections.
6. Restart application services and verify `/api/v1/health` readiness.

## Disaster recovery exercise

Executed 2026-08-03 (automated, repeated on every full validation run):

| Step                                                                            | Result |
| ------------------------------------------------------------------------------- | ------ |
| Provision clean PostgreSQL, install baseline, migrate to head, seed 100 tickets | Pass   |
| Back up with `backup_database.sh`; archive verified with `pg_restore --list`    | Pass   |
| Write data after the backup point (RPO marker table)                            | Pass   |
| Destroy and restore the database with `restore_database.sh`                     | Pass   |
| Data fingerprint (row count + ordered md5 digest) identical after restore       | Pass   |
| Post-backup write absent after restore (recovery point bounded by backup)       | Pass   |
| Migration head check passes against restored database                           | Pass   |
| Append-only enforcement (`ticket_event` DELETE rejected) after restore          | Pass   |

## Recovery objectives

| Objective                 | Target                             | Evidence                                                                                                                        |
| ------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| RPO (production, PITR)    | 15 minutes (WAL shipping interval) | Architecture plan above; WAL prerequisites asserted by test                                                                     |
| RPO (logical backup tier) | 24 hours (nightly backup)          | Restore test proves post-backup writes are excluded                                                                             |
| RTO (single database)     | 60 minutes                         | Automated drill restores the seeded database in under 180 seconds; production budget adds archive retrieval and validation time |

The automated drill enforces a hard 180-second ceiling on the restore step
itself; measured wall-clock time is reported in the test output.
