# Attachment quarantine, scanning, and protected delivery

Milestone 4, Task 4.4 introduces a fail-closed attachment lifecycle. File bodies remain in the
private S3-compatible object store; PostgreSQL contains only generated object keys, integrity and
security metadata, and immutable lifecycle evidence. Object-store credentials, signing secrets,
encryption keys, and raw bytes are never written to PostgreSQL.

## Lifecycle APIs

```http
POST /api/v1/tickets/{ticket_key}/attachments/uploads
POST /api/v1/attachments/{attachment_id}/finalize
POST /api/v1/attachments/{attachment_id}/download
```

Upload authorization requires an authenticated user with ticket access. The request supplies a
base filename, declared MIME type, byte size, lowercase SHA-256 checksum, and `PUBLIC` or
`INTERNAL` visibility. Internal uploads additionally require the internal-comment permission.
The API accepts only PDF, PNG, JPEG, GIF, UTF-8 text, and CSV extensions with matching declared
types, enforces the configured size limit, generates an opaque `quarantine/...` key, and returns a
short-lived signed PUT URL. Client object keys and URIs are never accepted.

Finalization requires `Idempotency-Key`. The API reads only the generated quarantine key, applies
the configured maximum again, verifies actual size and checksum, detects MIME from file signature
or bounded UTF-8 inspection, and requires the detected type to match the extension. It streams the
bytes to ClamAV using the bounded `INSTREAM` protocol and records scanner engine, version, scan
time, attempt count, and threat metadata. A clean file is copied with provider-managed encryption
to a generated `protected/...` key and removed from quarantine. An infected or invalid file is
deleted from quarantine and permanently rejected.

Scanner or storage failures set `ERROR`, retain quarantine, increment the bounded attempt count,
and set `next_scan_at`. The API returns `503` plus `Retry-After`; finalization may be retried only
after the delay and before the configured attempt limit. Infected and validation failures are
final. No state other than `CLEAN` plus `RELEASED` and a protected key can receive a download URL.

## Authorization and storage policy

Every operation resolves the attachment through its tenant-owned ticket. Employees may upload and
download public attachments only on tickets they report, request, or participate in. Analysts need
assignment-group visibility; project and platform administrators retain read-all authority.
Internal attachments are never returned to employee callers. Download authorization is evaluated
before issuing a short-lived signed GET URL, and the MinIO bootstrap explicitly disables anonymous
bucket access.

SHA-256 supports integrity verification and duplicate detection through an index. The initial
deduplication policy is detection-only: binaries are not reused across tickets, tenants, users, or
visibility classifications because doing so could create an authorization side channel. Each
authorized upload receives distinct quarantine and protected keys even when its checksum matches
another attachment.

Each authorization, release, rejection, retry scheduling, and download authorization writes an
append-only ticket event and audit event. Audit summaries contain identifiers and lifecycle state,
not filenames, file bytes, signed URLs, threat payload bytes, or storage credentials.

## Configuration

```text
ATTACHMENT_MAX_BYTES=26214400
ATTACHMENT_UPLOAD_URL_SECONDS=900
ATTACHMENT_DOWNLOAD_URL_SECONDS=300
CLAMAV_TIMEOUT_SECONDS=15
CLAMAV_MAX_ATTEMPTS=3
CLAMAV_RETRY_SECONDS=30
```

Production configuration requires object-storage credentials and `CLAMAV_REQUIRED=true`. Keep the
bucket private and set `OBJECT_STORAGE_SERVER_SIDE_ENCRYPTION` to `AES256` or `aws:kms` (with
`OBJECT_STORAGE_SSE_KEY_ID` for KMS). Local MinIO leaves this unset and records encryption as not
applicable unless its KMS service is configured. Configure lifecycle retention outside the API.
Migration `0008_attachment_lifecycle` adds reversible scan retry fields, lifecycle constraints,
ticket/checksum/retry indexes, and preserves the physical baseline unchanged.
