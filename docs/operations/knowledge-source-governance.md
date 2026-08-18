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

## Knowledge-gap dispositions

Milestone 14 Task 14.3 adds the one governed mutation on the analytics surface:
`PUT /api/v1/admin/knowledge/retrieval-analytics/dispositions` requires
`KNOWLEDGE_SOURCE_UPDATE` and an `Idempotency-Key`, and records one audited current-state
disposition per tenant and normalized query from the bounded set `ACKNOWLEDGED`,
`SOURCE_CANDIDATE`, `NOT_A_GAP`, and `RESOLVED`, with an optional bounded note. Creation
requires no `expected_row_version`; every later change must supply the current row version and
conflicts deterministically when stale, while replaying the same idempotency key returns the
recorded result with `Idempotent-Replayed`. Every mutation appends an immutable
`KNOWLEDGE_GAP_DISPOSITION` audit event; disposition rows are never deleted. Group listings
carry the current disposition, and the Analytics tab offers the disposition dialog to
authorized administrators. A disposition records a human decision only — it never creates
sources, starts acquisition, or changes retrieval behavior.

## Synonym and acronym registry

Milestone 15 Task 15.1 adds the governed, tenant-isolated synonym and acronym
registry. `GET /api/v1/admin/knowledge/retrieval-synonyms` requires
`KNOWLEDGE_DOCUMENT_READ_ADMIN` and lists bounded term-to-expansion entries
with status and term-prefix filters. `PUT /api/v1/admin/knowledge/retrieval-synonyms`
requires `KNOWLEDGE_SOURCE_UPDATE` and an `Idempotency-Key`; terms and
expansions are normalized (lowercased, trimmed, whitespace-collapsed) and
bounded, new entries always start in `DRAFT`, and each later change must
supply the current row version and follows the deterministic lifecycle
`DRAFT` → `APPROVED` → `RETIRED` (a retired entry may be reopened to
`DRAFT`). A term keeps at most ten active expansions. Replaying the same
idempotency key returns the recorded result with `Idempotent-Replayed`.
Every mutation appends an immutable `KNOWLEDGE_SYNONYM_CHANGE` audit event;
entries are retired, never deleted. The knowledge administration Synonyms tab
presents the registry with the create and change dialogs for authorized
administrators.

The registry records administrative vocabulary decisions only. Nothing in
Task 15.1 reads the registry from the retrieval path: ranking, fusion,
eligibility, and the retrieval regression suite are unchanged. Only the
separately approved Task 15.2 (below) may apply `APPROVED` entries during
retrieval, tenant-opt-in and default off.

## Governed synonym expansion in retrieval

Milestone 15 Task 15.2 applies the registry inside the shared retrieval
service — the single retrieval-behavior change ratified for Milestone 15.
When the global switch `RETRIEVAL_SYNONYM_EXPANSION_ENABLED` is on (default
off) and the tenant appears in the
`RETRIEVAL_SYNONYM_EXPANSION_TENANT_IDS` opt-in allowlist (default empty),
`APPROVED` entries whose term appears whole-word in the normalized query
append their expansions — deduplicated, at most five, never exceeding the
500-character query bound — to the query used for embedding, lexical and
vector search, and fusion input. The original normalized query is always
preserved in the API response and in query-event grouping, so analytics
group identity is stable across expansion on and off. `DRAFT` and `RETIRED`
entries and other tenants' entries never apply. Turning the global switch
off deterministically restores unexpanded behavior, and a registry lookup
failure falls back to the unexpanded query.

Migration `0034_query_event_expansion` adds two nullable observation columns
to `kb.retrieval_query_event` (`expansion_applied`, `expanded_term_count`)
so the Task 15.3 analytics can report expansion effectiveness. Ranking
weights, fusion, candidate selection, top-k, thresholds, embeddings, and
reranking are unchanged, and the retrieval regression suite runs unmodified
with both settings at their off defaults.

## Expansion effectiveness analytics

Milestone 15 Task 15.3 extends the Milestone 14 retrieval analytics
read-only with the expansion evidence captured by Task 15.2. The summary
adds the expansion-applied count and rate, and every zero-result and
low-confidence query group reports how many of its events ran with
expansion applied and how zero results split between expanded and
unexpanded events — the zero-result movement an administrator needs to
judge whether approved vocabulary closes an observed gap. Rows captured
before Task 15.2 count as unexpanded. The Analytics tab presents the new
summary fragment and an Expanded column; there is no new mutation surface,
no export, no cross-tenant aggregation, and no retrieval behavior change.

## Chunk error-code index

Milestone 16 Task 16.1 gives knowledge administrators deterministic evidence
of which error codes the corpus actually documents. The processing worker
extracts error-code identifiers from each chunk's document title, heading
path, section title, and content with the same grammar the fusion boost
applies to queries and candidates, and stores them as immutable per-chunk
facts in `kb.chunk_error_code` in the same transaction as the chunk itself.
Migration `0035_chunk_error_codes` backfills codes for chunks that existed
before it ran. Only the processing worker may write index rows; updates and
deletes are trigger-rejected, and rows disappear only when their chunk is
superseded through reprocessing.

`GET /api/v1/admin/knowledge/error-codes`, behind
`KNOWLEDGE_DOCUMENT_READ_ADMIN`, lists each indexed code with its indexed
chunk count and its published chunk count. Publishedness is evaluated
against `kb.v_active_document_chunk` at read time, so publication, rollback,
suppression, and approval changes are always reflected without
resynchronization. The prefix filter normalizes case and separators exactly
like the stored codes. Retrieval behavior is unchanged in this task: nothing
reads the index from the retrieval path, and the retrieval regression suite
runs byte-unmodified. Only the separately approved Task 16.2 may consult the
index during retrieval.

## Governed error-code matching in retrieval

Milestone 16 Task 16.2 is the single retrieval-behavior change ratified for
Milestone 16. Behind the `RETRIEVAL_ERROR_CODE_MATCHING_ENABLED` global kill
switch (default off) and the `RETRIEVAL_ERROR_CODE_MATCHING_TENANT_IDS`
opt-in allowlist (default empty), a query containing an error code gains a
third candidate channel: published chunks indexed under that exact code by
the Task 16.1 index join the candidate set inside the single shared
retrieval service boundary. The channel runs the same eligibility CTE as
the lexical and vector channels, so ACLs, retrieval filters, and corpus
suppression apply identically, and it can only broaden candidate selection
— never remove or reorder what the other channels found.

Ranking is untouched: matched candidates flow through the unchanged fusion
formula, where a candidate without a lexical or vector rank scores through
the existing exact-identifier, metadata, and source-authority boosts alone.
The original normalized query is always preserved in the API response and
in query-event grouping. Turning the global switch off deterministically
restores unmatched candidate selection, a query without an error code skips
the channel entirely, and an index lookup failure falls back to the
unmatched candidate set.

Migration `0036_event_error_codes` adds two nullable observation columns to
`kb.retrieval_query_event` (`error_code_matching_applied`,
`matched_error_code_count`) so the Task 16.3 analytics can report matching
effectiveness. Ranking weights, fusion scoring, candidate selection outside
the governed channel, top-k, thresholds, embeddings, reranking, and synonym
expansion are unchanged, and the retrieval regression suite runs
byte-unmodified with both settings at their off defaults.

## Error-code effectiveness analytics

Milestone 16 Task 16.3 extends the Milestone 14 retrieval analytics
read-only with the matching evidence captured by Task 16.2. The summary
adds the error-code-matched count and rate, and every zero-result and
low-confidence query group reports how many of its events ran with
matching applied and how zero results split between matched and unmatched
events — the zero-result movement an administrator needs to judge whether
exact error-code matching closes an observed gap. Rows captured before
Task 16.2 count as unmatched. The Analytics tab presents the new summary
fragment and a Matched column; there is no new mutation surface, no
export, no cross-tenant aggregation, and no retrieval behavior change.
