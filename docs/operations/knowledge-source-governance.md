# Knowledge source governance

Milestone 6, Task 6.1 adds the administrative registry and the permission gate only. It does not
download, upload, parse, store, or publish document content.

## Administrative API

The `/api/v1/admin/knowledge/sources` endpoints support tenant-visible listing, creation, complete
definition replacement, approval decisions, acquisition-authorization decisions, and acquisition
permission evaluation. Mutations require an `Idempotency-Key` and an expected row version where an
existing source is changed. A definition change resets approval to `DRAFT` and disables automated
access so that previously granted permission cannot silently authorize changed source details.

Knowledge authors may read, create, and update tenant sources. Knowledge approvers may read,
approve, and manage acquisition permission. Platform administrators hold both capabilities and are
the only role permitted to create or change global sources. Customers and other employees cannot
use source-administration endpoints. A user, or a member of an owning support group, cannot approve
that same source.

## Permission gate

External acquisition is denied unless every condition below is true:

- the source is `ACTIVE` and `APPROVED`;
- its method is an external acquisition method;
- the current immutable source version has an effective `APPROVED` authorization record;
- the authorization method matches the source method; and
- the source has not subsequently changed.

Oracle documentation has an additional deployment kill switch. It remains denied by default even
after source approval and an acquisition authorization. Enabling the switch records no permission
by itself; all ordinary gate conditions still apply.

The permission endpoint returns stable reason codes rather than attempting acquisition. Task 6.2
must call this server-side gate before performing any external I/O.

## Data and audit behavior

Sources retain tenant/global scope, audience (`EMPLOYEE`, `ANALYST`, `RESTRICTED`, or
`ADMINISTRATIVE`), owner, lifecycle, product/module/release metadata, and language. Acquisition
authorizations capture the exact source row version, method, canonical location, permission
reference, actor, and effective period. They are append-only. Source changes and authorization
decisions create audit events containing bounded governance summaries; credentials and document
content are not accepted or recorded.

The migration applies tenant-or-global row-level policies to both registry tables. The application
also scopes every query explicitly and enforces role permissions in the service layer.

## Refresh lifecycle administration

Milestone 13 Task 13.1 adds an administrative refresh lifecycle to each governed source. The
stored state is `CURRENT`, `REFRESH_DUE`, `REFRESHING`, or `STALE`; a retired source always
reports the derived effective state `RETIRED`. Administrators holding `KNOWLEDGE_SOURCE_UPDATE`
may mark a source for refresh, mark it current, or mark it stale through
`POST /api/v1/admin/knowledge/sources/{source_id}/refresh-lifecycle`. Transitions require an
`Idempotency-Key` and the expected row version, reject retired sources and out-of-order
transitions deterministically, and write a `KNOWLEDGE_SOURCE_REFRESH_LIFECYCLE_CHANGED` audit
event with the from/to states.

The lifecycle records administrative intent only. No transition acquires content, creates an
ingestion run, changes retrieval eligibility, or alters approval or acquisition permission. The
reserved `REFRESHING` value is not reachable through the administrative endpoint; refresh runs
(below) own it. The source inventory endpoint additionally reports the latest acquisition
evidence (most recent ingestion item status and time) derived read-only from existing pipeline
tables.

## Content-change detection

Milestone 13 Task 13.2 adds governed refresh runs over already-approved sources.
`POST /api/v1/admin/knowledge/sources/{source_id}/refresh-runs` requires
`KNOWLEDGE_INGESTION_RUN_CREATE`, an `Idempotency-Key`, and the expected source row version. It
creates a `REFRESH` ingestion run over the source's approved, enabled manifest entries — the
same acquisition permission gate as ordinary runs applies to every entry — and moves the source
to `REFRESHING`. Retired sources, sources already refreshing, and sources without approved
entries are rejected deterministically. Starting or completing a refresh never increments the
source row version, so the row-version-pinned acquisition authorization stays valid for the run.

The acquisition worker classifies each page by content hash against the latest stored document
version: `UNCHANGED`, `CHANGED` (a new draft document version is stored), `REMOVED` (HTTP 404 or
410, recorded as terminal `SKIPPED_REMOVED`), or `REDIRECTED` (HTTP 3xx; the target is recorded
and never followed, terminal `SKIPPED_REDIRECTED`). Classification, previous checksum, redirect
target, and observed HTTP status persist on the run item as evidence. Changed content never
republishes automatically — publication remains the separate, explicitly approved
administrative action.

When the refresh run drains, the worker feeds the Task 13.1 lifecycle deterministically: all
pages unchanged with no final failures returns the source to `CURRENT`; any changed, removed,
redirected, or finally-failed page marks it `STALE`. The completion writes a system-attributed
`KNOWLEDGE_SOURCE_REFRESH_LIFECYCLE_CHANGED` audit event.
`GET /api/v1/admin/knowledge/sources/{source_id}/change-report` returns the latest refresh run
with per-page evidence and summary counts for the knowledge-administration screens.

## Corpus validation

Milestone 13 Task 13.3 adds a persisted, pre-publication corpus validation report.
`POST /api/v1/admin/knowledge/corpus-validations` requires `KNOWLEDGE_DOCUMENT_PUBLISH` and an
`Idempotency-Key`; it scans the tenant-visible corpus (current versions of active tenant and
global documents, their latest processing versions, and chunks) in one transaction and records
four deterministic finding types: structural defects (failed processing or per-document
validation), empty chunks, duplicate documents (identical content checksums across documents),
and near-duplicate chunk pairs (embedding cosine similarity at or above the recorded 0.95
threshold across different documents). Reports are read through
`GET /api/v1/admin/knowledge/corpus-validations/latest` and
`GET /api/v1/admin/knowledge/corpus-validations/{run_id}` with a finding-type filter; findings
are append-only and immutable at the database level, and each run writes a
`KNOWLEDGE_CORPUS_VALIDATION_RUN` audit event.

Suppression flags are advisory in this task. Within every near-duplicate group the canonical
member — earliest document, then lowest identifiers — is never flagged, so the last visible copy
of content always survives, and a tenant never flags shared global content. The flag changes no
retrieval eligibility: retrieval views are untouched, and only a later approved publication may
apply suppression. Reranking, synonym management, embedding changes, and automatic publication
remain out of scope.

## Corpus publication and rollback

Milestone 13 Task 13.4 adds governed, corpus-level publication.
`POST /api/v1/admin/knowledge/corpus-publications` requires `KNOWLEDGE_DOCUMENT_PUBLISH` and an
`Idempotency-Key`; it is blocked with a deterministic conflict unless the latest corpus
validation run is completed, untruncated, and not stale (no processing activity after the run
started). Publication creates an immutable `kb.corpus_version` record that snapshots the
advisory suppression flags into `kb.corpus_version_suppressed_chunk` and atomically becomes the
tenant's single active version: retrieval then excludes exactly the snapshotted chunks, and the
canonical member of every near-duplicate group — never flagged by validation — always remains
retrievable. With no active version, retrieval eligibility is unchanged.

`POST /api/v1/admin/knowledge/corpus-publications/rollback` performs the one-step rollback: it
reactivates the immediately prior published version through the same atomic switch, so retrieval
eligibility deterministically returns to that version's recorded snapshot. Versions are never
deleted or rewritten; every publication and rollback appends an immutable
`kb.corpus_publication_event` row and writes a `KNOWLEDGE_CORPUS_PUBLICATION` or
`KNOWLEDGE_CORPUS_ROLLBACK` audit event. `GET .../corpus-publications/active` reports the active
version with publication readiness and blockers; `GET .../corpus-publications` lists the version
and event history. Automatic or scheduled publication remains out of scope.

## Retrieval query events

Milestone 14 Task 14.1 records one append-only, tenant-isolated
`kb.retrieval_query_event` row per successful retrieval invocation across employee evidence
search, the employee agent, and the analyst copilot. Each event stores only the bounded
normalized query text (never the raw input), the requesting surface, the result count, the
zero-result flag, the top fused score, and the tenant's active corpus version at query time; no
user identity is recorded. Capture is strictly observational: a capture failure is contained and
logged and never changes the retrieval response, and no retrieval ranking, eligibility, or
configuration behavior is affected. Events carry no runtime read endpoint yet — they are the raw
evidence for the later Task 14.2 zero-result and low-confidence analytics. Rows are immutable
against updates and expire through a bounded, tenant-scoped retention sweep controlled by
`RETRIEVAL_QUERY_EVENT_RETENTION_DAYS` (default 180 days); captured events are never exported.

## Retrieval search analytics

Milestone 14 Task 14.2 adds read-only analytics over the captured query events. Three
`GET` endpoints under `/api/v1/admin/knowledge/retrieval-analytics` — `summary`,
`zero-result-queries`, and `low-confidence-queries` — require `KNOWLEDGE_DOCUMENT_READ_ADMIN`
and aggregate strictly within the caller's tenant over a bounded trailing window
(`days`, 1–365, default 30). Groups are keyed by the stored normalized query and report
occurrence counts, best fused score, requesting surfaces, first/last-seen timestamps, and the
last active corpus version observed. An event is classified low-confidence when it returned
results whose top fused score is below `RETRIEVAL_LOW_CONFIDENCE_THRESHOLD` (default 0.01,
mirroring the employee agent's minimum evidence score); the threshold is an analytics-only
classification and is never read by the retrieval path. The knowledge administration
Analytics tab presents the summary and both group tables read-only: no mutation, no export,
and no retrieval behavior change.
