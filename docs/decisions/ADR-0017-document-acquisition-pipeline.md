# ADR-0017: Document acquisition and quarantine lifecycle

Status: Accepted for Milestone 6, Task 6.2.

Migration revision: `0013_document_acquisition`.

## Decision

Extend the adopted knowledge ingestion tables through Alembic with explicit manifest approval,
version snapshots, quarantine metadata, retry leases, malware results, and immutable ingestion
events. The migration replaces the existing ingestion-item status constraint so manual uploads can
wait for completion before a worker claim. This is the rewrite-sensitive operation approved by this
ADR; it does not remove stored business data.

The API issues private, generated quarantine keys and never accepts an object key from a caller.
Workers re-evaluate source and manifest permission immediately before acquisition, validate bounded
content, scan it, and copy clean originals to deterministic canonical keys. PostgreSQL stores only
keys, checksums, metadata, lifecycle state, and safe error codes.

External acquisition is limited to exact approved HTTPS URLs on the registered source host. It
does not follow redirects, rejects private network destinations, and stores no provider credentials.
Oracle acquisition also retains the deployment-level default-deny switch.

Task 6.2 stops at an acquired, unparsed `document_version`. Extraction, chunking, embeddings,
validation, and publication remain Task 6.3.
