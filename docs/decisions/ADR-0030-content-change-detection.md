# ADR-0030: Content-change detection over approved sources

Status: Accepted for Milestone 13, Task 13.2.

Migration revision: `0028_content_change_detection`.

## Decision

Extend the governed acquisition pipeline so refresh runs re-acquire only
already-approved sources and classify each page as unchanged, changed, removed,
or redirected using content hashing. The migration replaces two existing check
constraints — the ingestion-run type constraint gains the `REFRESH` run type,
and the ingestion-item status constraint gains the terminal, non-failure
`SKIPPED_REMOVED` and `SKIPPED_REDIRECTED` outcomes. These constraint
replacements are the rewrite-sensitive operations approved by this ADR; they
remove no stored business data and widen the allowed value sets only.

Per-page change evidence (classification, previous checksum, redirect target,
observed HTTP status) is persisted on the ingestion run item and stays NULL for
ordinary acquisition runs. Redirects are recorded and never followed; removed
pages are recorded and never retried. A completed refresh run feeds the
Task 13.1 source refresh lifecycle deterministically: all pages unchanged and
no final failures returns the source to `CURRENT`; any changed, removed,
redirected, or finally-failed page marks it `STALE`.

Refresh-lifecycle transitions driven by refresh runs never increment the
source row version, because acquisition allowlist authorizations are pinned to
the exact source row version and starting a refresh must not invalidate the
authorization the run relies on. The worker receives a column-scoped UPDATE
grant on `kb.source` limited to the three refresh lifecycle columns.

Changed content is acquired as a new draft document version and never
republishes automatically; publication remains an explicit, separately
audited administrative action.
