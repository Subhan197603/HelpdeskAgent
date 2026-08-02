# Document acquisition operations

Milestone 6, Task 6.2 provides permission-gated manifest imports, manual uploads, and background
acquisition. It stores originals in private object storage and stops before parsing or publication.

## Runtime configuration

Configure the API and worker with the same private bucket, endpoint, region, access key, secret key,
and server-side-encryption mode. Production configuration rejects missing or development-placeholder
credentials and requires `AES256` or `aws:kms`; KMS also requires a key identifier. Keep
`ORACLE_DOCUMENT_ACQUISITION_ENABLED=false` unless governance has separately approved Oracle-hosted
automation.

The worker role must use `WORKER_DATABASE_URL`; it has only the migration-granted acquisition and
document metadata privileges. File bytes and provider credentials must never be placed in
PostgreSQL.

## Lifecycle and recovery

Manifest imports reset external entries to `PENDING`. A different authorized approver must approve
each entry before a run can be created. Workers recheck the source authorization, source version,
manifest approval, manifest version, and acquisition method before reading or fetching content.

Manual uploads remain `AWAITING_UPLOAD` until the client completes the upload. Acquired content is
held under a generated `quarantine/knowledge/...` key, size/type/checksum validated, malware scanned,
and copied unchanged to:

```text
knowledge/{tenant_or_global}/{source_code}/{document_id}/{version_id}/original/{filename}
```

Retryable failures retain the item with an exponential `next_attempt_at`; final validation,
permission, checksum, or malware failures do not retry. A worker lease makes interrupted work
reclaimable. Starting another worker is sufficient to resume due work. Exact document checksums are
marked `SKIPPED_UNCHANGED` and do not create another version.

## Investigation

Inspect `kb.ingestion_run` and `kb.ingestion_run_item` for safe status and error codes. Use the
append-only `kb.ingestion_event` history for attempt outcomes. Never copy quarantine URLs, object
credentials, or document content into logs or tickets. Revoke or disable the source when permission
is uncertain; pending workers will fail closed on their next permission check.
