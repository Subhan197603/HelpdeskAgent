# Database migrations

## Ownership boundary

The SQL package in `database/baseline/fusion_helpdesk_postgres` is the one-time physical baseline.
It owns the initial schemas, extensions, tables, constraints, indexes, functions, and reference
data. Alembic owns every reviewed database change after that baseline. Never place
`install_all.sql` in a revision or rerun the installer as a deployment migration.

Alembic records state in `config.alembic_version`. The `config` schema must already exist, which is
one reason the marker cannot replace physical-baseline installation. The root revision,
`0000_physical_baseline`, has empty upgrade and downgrade functions. Identity behavior is documented in the
[developer identity guide](developer-identity.md), queue indexes are documented in the
[analyst queue guide](analyst-queues-activity.md), and attachment lifecycle indexes and
constraints are documented in the [attachment security guide](attachment-security.md).

## Release lineage

Production `main` and `v1.0.0` are frozen at commit
`cc9d76885e181230bd91f5b9bfd0605a9b23fb07`. Their historical Alembic head is
`0020_reporting_views`.

The validated Milestone 11 R4 application baseline is annotated tag
`milestone-11-remediation-r4` at
`ce1375edc574a3fc8befede0c5efc90861c69308`. Its Alembic head is
`0023_knowledge_admin_index`. The later final-closure governance commit is
documentation-only and does not change that migration state.

The validated Milestone 12 application baseline is commit
`3136c29f10d434a870b0b72f61d0d5de7d827c08` with Alembic head
`0026_analyst_ticket_watchlist`. Task 12.4 and the analyst Linux baseline
realignment introduced no migrations, and the Milestone 12 closure governance
commit is documentation-only.

The only post-v1 revisions currently present are:

```text
0020_reporting_views
→ 0021_admin_access_privileges
→ 0022_admin_config_privileges
→ 0023_knowledge_admin_index
→ 0024_analyst_saved_filters
→ 0025_analyst_canned_responses
→ 0026_analyst_ticket_watchlist
→ 0027_knowledge_source_lifecycle
→ 0028_content_change_detection
→ 0029_corpus_validation
```

Revision `0021_admin_access_privileges` supplies narrowly scoped runtime grants
for access-administration mutations. Revision
`0022_admin_config_privileges` grants only
`UPDATE(active_flag, employee_visible_flag)` on `config.request_type` to the
application runtime role. Task 11.5D introduced revision
`0023_knowledge_admin_index`. It adds only the GIN trigram index used by
tenant-scoped knowledge-administration title search. It grants no new document,
version, ACL, or delete privileges and does not alter public retrieval
eligibility. Never rewrite production history to imply that `v1.0.0` contains
any post-v1 revision.

Task 11.5E adds read-only AI governance over existing AI policy, usage, and
configuration tables. It reuses `AI_OVERSIGHT` and existing runtime `SELECT`
privileges, adds no database object or write privilege, and therefore retains
`0023_knowledge_admin_index` as the development head.

Milestone 12 Task 12.1 introduced `0024_analyst_saved_filters`. It adds one
private preference table with tenant-and-owner
row-level security, narrow runtime CRUD grants, optimistic row versions, and
owner-scoped uniqueness and ordering indexes. It follows
`0023_knowledge_admin_index`; the physical PostgreSQL baseline is unchanged.

Milestone 12 Task 12.2 introduced `0025_analyst_canned_responses`. It adds
private bounded plaintext snippets with tenant-and-owner row-level security,
narrow runtime CRUD grants, optimistic row versions, and owner-scoped
uniqueness and ordering indexes. It follows `0024_analyst_saved_filters`; the
physical PostgreSQL baseline is unchanged.

Milestone 12 Task 12.3 introduced `0026_analyst_ticket_watchlist`. It adds
private ticket-watch preferences with tenant-and-owner
row-level security, visibility-safe indexes, and narrow runtime select, insert,
and delete grants. It follows `0025_analyst_canned_responses`; the physical
PostgreSQL baseline is unchanged.

Milestone 13 Task 13.1 introduces `0027_knowledge_source_lifecycle`. It adds
five additive refresh-lifecycle columns and one check constraint and index to
`kb.source`, recording administrative refresh intent only. Existing
`kb.source` row-level security and runtime grants cover the new columns; no
new table, privilege, or retrieval behavior is introduced. It follows
`0026_analyst_ticket_watchlist`; the physical PostgreSQL baseline is
unchanged.

Milestone 13 Task 13.2 introduces `0028_content_change_detection`. It adds four additive per-page change-evidence columns to
`kb.ingestion_run_item` (classification, previous checksum, redirect target,
observed HTTP status), widens the ingestion-run type constraint with the
`REFRESH` run type and the ingestion-item status constraint with the terminal
`SKIPPED_REMOVED` and `SKIPPED_REDIRECTED` outcomes (approved by ADR-0030),
and grants the worker role a column-scoped `UPDATE` on the three `kb.source`
refresh-lifecycle columns. No retrieval behavior changes; it follows
`0027_knowledge_source_lifecycle`; the physical PostgreSQL baseline is
unchanged.

Milestone 13 Task 13.3 introduces `0029_corpus_validation`, the current
development head. It adds two tenant-isolated tables — `kb.corpus_validation_run`
and the append-only, trigger-immutable `kb.corpus_validation_finding` — plus an
advisory `near_duplicate_suppressed_flag` column on `kb.document_chunk` with a
column-scoped application-role grant. Findings are evidence only: the flag never
changes retrieval eligibility, which only a later approved publication may
apply. It follows `0028_content_change_detection`; the physical PostgreSQL
baseline is unchanged.

## Adopt a new local database

```sh
make db-install
make db-validate-baseline
make db-stamp-baseline
make migration-current
make migrate
```

`db-install` creates the physical objects and the local non-owner application login. Validation
checks every file in `SHA256SUMS.txt`, required schemas and extensions, representative and
governance tables, both Oracle release families in both release registries, and any existing
Alembic revision. Stamping is refused if validation fails. Immediately after stamping,
`migration-current` reports `0000_physical_baseline`; `migrate` then advances to the latest later
revision.

## Adopt an existing baseline database

1. Obtain the approved baseline package and verify its provenance.
2. Run `make db-validate-baseline` against the target database.
3. Investigate any missing object, checksum mismatch, or conflicting revision; the validator does
   not repair a database.
4. Run `make db-stamp-baseline`.
5. Confirm the marker with `make migration-current`, then use `make migrate` for later revisions.

Repeating validated stamp while already at the marker is safe. Validated stamp refuses to replace
a later revision. A raw `alembic stamp` remains technically available to administrators but
bypasses project validation and must not be used by deployment automation.

For future brand-new deployments, install the baseline once, validate it, stamp the marker, and
run upgrades. Existing production databases skip installation and follow the adoption workflow.

## Commands

| Command                     | Behavior                                                    |
| --------------------------- | ----------------------------------------------------------- |
| `make migrate`              | Validate the baseline and upgrade to `head`                 |
| `make migration`            | Create an explicit reviewed revision skeleton               |
| `make migration-check`      | Check naming, linear history, schemas, and destructive work |
| `make migration-current`    | Report the database revision                                |
| `make migration-history`    | Display the complete revision chain                         |
| `make db-validate-baseline` | Validate package identity and required database objects     |
| `make db-stamp-baseline`    | Validate, then stamp `0000_physical_baseline`               |

Database commands run through the Compose `migrator` service and therefore use PostgreSQL's
container port, not host port 5432. Direct host execution is also supported:

```sh
MIGRATION_DATABASE_URL=postgresql+psycopg://migrator@127.0.0.1:5432/helpdesk \
  uv run python -m apps.api.app.db.migrations_cli validate
```

Use secret-manager injection for real credentials. URLs are loaded as redacted typed settings and
are not placed in `alembic.ini` or logs.

## Create and review a migration

Choose a meaningful, linear identifier no longer than 32 characters:

```sh
make migration \
  MIGRATION_ID=0002_identity_subject_index \
  MIGRATION_MESSAGE="add identity subject lookup index"
make migration-check
```

Revision files require explicit schema, constraint, and index names, PostgreSQL-compatible
operations, downgrade logic unless explicitly impossible, and comments for lock-sensitive work.
Separate data changes from schema changes when practical. Never include secrets, deployment
identifiers, runtime-input string interpolation, or baseline-installer calls.

Complete ORM metadata does not exist yet. Autogeneration is disabled while managed metadata is
empty. As module models are added, Alembic will compare only managed objects; reflected baseline
objects with no model are excluded, so missing metadata cannot generate mass `DROP TABLE`
operations. Use reviewed explicit operations when a table is not yet modeled. pgvector and
extension-owned/system objects are outside the current comparison set.

For upgrade paths, the guard rejects table/schema/column/constraint/extension removal, type or enum destruction,
type/rewrite-sensitive SQL, non-null conversion without review, and foreign-key additions that
need size/index review. An exceptional approved revision must contain:

```text
DESTRUCTIVE_MIGRATION_APPROVED: ADR-NNNN
```

The matching ADR file must exist and explicitly name the revision. There is no environment-variable
bypass.

## Execution locking and failure recovery

Every online Alembic command takes PostgreSQL advisory lock `6817315412136801249`. The default
timeout is ten seconds and is configured by `MIGRATION_LOCK_TIMEOUT_SECONDS`; failure is explicit.
The session lock is released on success, rollback, failure, or connection close. Redis is not
involved.

Alembic uses transactional DDL and transaction-per-migration behavior. After failure:

1. Stop additional deployers and inspect `make migration-current` and PostgreSQL logs.
2. Correct the revision or operational cause; do not edit an already deployed revision casually.
3. Retry `make migrate` when the lock holder has exited.
4. Use a reviewed downgrade only when its compatibility and data effects are understood.

Do not downgrade below `0000_physical_baseline` in a real environment. The marker downgrade is
technically a no-op and never uninstalls baseline objects, but removing the version row loses the
recorded adoption boundary.

## Known limitations

Database object validation proves that required baseline characteristics exist; it cannot prove
the complete historical path by which an existing database acquired them. The local package
checksum check and external release provenance remain necessary. Metadata is intentionally partial,
and PostgreSQL-specific or pgvector changes may require explicit operations until their module
models are adopted.
