# Fusion Helpdesk PostgreSQL Starter Package

This package is a PostgreSQL foundation for a custom, Jira Service Management–style IT helpdesk with:

- Employee service portal and ticketing
- Configurable request types and workflows
- Assignment rules and analyst queues
- SLA and approval data models
- Knowledge-document governance and pgvector retrieval
- Oracle Fusion Applications 26C and FDI 26.R2 release separation
- AI conversations, tool calls, evidence and feedback
- Immutable ticket events, security audit and transactional outbox

## Release convention

Keep the product release streams separate:

- `FUSION_APPLICATIONS / 26C`
- `FUSION_DATA_INTELLIGENCE / 26.R2`

Do not store either value as a generic `26R` release.

## Prerequisites

- PostgreSQL 16 or later
- `pgvector` installed on the PostgreSQL server
- Permission to create these extensions:
  - `pgcrypto`
  - `pg_trgm`
  - `unaccent`
  - `vector`
- `psql` for the modular installer

The package uses `UNIQUE NULLS NOT DISTINCT`, introduced in PostgreSQL 15.

## Package layout

```text
sql/
  00_prerequisites.sql
  01_foundation.sql
  02_catalog_workflow.sql
  03_ticketing.sql
  04_routing_sla_approval.sql
  05_knowledge.sql
  06_ai_audit_integration.sql
  06a_foundational_governance.sql
  07_indexes_views_search.sql
  08_seed_reference.sql
  08a_runtime_privileges.sql
  09_optional_rls.sql
  10_demo_bootstrap.sql
  11_demo_ticket.sql
  install_all.sql
  uninstall_all.sql

manifest/
  documentation_manifest_template.csv
  company_document_manifest_template.csv
  oracle_fusion_module_inventory.csv

scripts/
  requirements.txt
  load_manifest.py
  acquire_approved_documents.py
  register_local_documents.py
```

## Install the base schema

From the repository root, start PostgreSQL and install the baseline with the container's `psql`:

```bash
make db-install
```

The baseline directory is mounted read-only at `/baseline`. This path works regardless of the configured PostgreSQL host port.

For direct installation, `install_all.sql` uses `\ir`, so included files resolve relative to the installer:

```bash
psql "$DATABASE_ADMIN_HOST_URL" -v ON_ERROR_STOP=1 \
  -f database/baseline/fusion_helpdesk_postgres/sql/install_all.sql
```

The base installer does **not** enable row-level security automatically.

The installer is intentionally a one-time physical baseline. Repeated installation is unsupported and returns a non-zero result. Do not use it as a production migration.

## Install the optional demo

```bash
make db-demo-bootstrap
make db-demo-ticket
```

The demo creates example users with `.invalid` email addresses, support groups, workflows, request types, routing rules, queues and SLA goals.

The normal baseline installer never loads the demo tenant or ticket.

## Environment and alternate ports

Required local settings are copied from the repository `.env.example`. Relevant values are:

```dotenv
POSTGRES_HOST_PORT=5432
DATABASE_ADMIN_URL=postgresql://postgres:postgres@postgres:5432/helpdesk
DATABASE_ADMIN_HOST_URL=postgresql://postgres:postgres@127.0.0.1:5432/helpdesk
```

Set `POSTGRES_HOST_PORT` to another free loopback port when 5432 is occupied. Update `DATABASE_ADMIN_HOST_URL` to the same host port when using host-installed `psql`. Make targets run `psql` inside the container and therefore continue to use internal port 5432.

The checked-in values are local placeholders. Do not commit shared or production credentials.

## Local reset

Reset is deliberately restricted to the fixed local development database and requires explicit confirmation:

```bash
make db-reset APP_ENV=development CONFIRM_DB_RESET=local-helpdesk
```

The target terminates sessions to the local `helpdesk` database, recreates that database, and installs the baseline. It does not remove Docker volumes and must not be used against shared or production infrastructure. Cluster-level group roles are retained when the database is recreated.

## Baseline integration test

Run the isolated clean-database test with:

```bash
make db-test
```

The test creates a dedicated Compose project and volume, installs the baseline in PostgreSQL 16 with pgvector, validates schemas, extensions, representative tables, constraints, indexes, reference data, release-family separation, demo isolation, runtime privileges, health, optional demo scripts, and non-zero repeat-install behavior, then removes only the dedicated test project and volume.

## Baseline and Alembic responsibilities

This package remains the initial physical installation. Task 1.2 will add the empty Alembic marker revision `0000_physical_baseline` for an already-installed baseline. All schema changes after this accepted baseline must use reviewed Alembic migrations; the modular installer must not be replayed as a deployment migration.

## Foundational governance model

The baseline includes database foundations for:

- Immutable, domain-specific configuration versions and runtime version references
- API idempotency and conflict detection
- Operational application environments and product-release history
- Deterministic impact/urgency priority calculation
- Email correlation metadata with raw messages kept in protected object storage
- Retention policy and legal-hold assignments
- Attachment quarantine and malware-scan metadata
- AI feature switches, limits, budgets, versioned policies, and usage ledger
- General immutable audit events
- Effective-dated ownership on the existing service hierarchy
- Least-privilege owner, migrator, runtime, reporting, and read-only group roles

No provider keys, object-storage credentials, encryption keys, signing secrets, production tenant IDs, or production user IDs are stored in the baseline.

## Row-level security

Apply `09_optional_rls.sql` only after the application connection layer sets the tenant and user context on every transaction:

```sql
BEGIN;
SET LOCAL app.tenant_id = 'tenant-uuid';
SET LOCAL app.user_id = 'user-uuid';
-- application SQL
COMMIT;
```

Test RLS with a non-owner application role. PostgreSQL table owners normally bypass RLS unless `FORCE ROW LEVEL SECURITY` is enabled.

## Knowledge storage pattern

Use object storage for original files and PostgreSQL for:

- Source and permission records
- Product/module hierarchy
- Release metadata
- Document metadata and versions
- Extracted semantic chunks
- Full-text indexes
- Vector embeddings
- Document ACLs
- Manifest and ingestion-run status

The starter embedding table uses `vector(1536)`. Select and approve a 1536-dimensional embedding model before production. For a different dimension, create a separate physical embedding table and index rather than mixing dimensions in the same column.

## Load the manifest template

Create a Python environment and install the small loader dependency set:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

Validate the CSV without committing:

```bash
python scripts/load_manifest.py \
  manifest/documentation_manifest_template.csv \
  --dsn "$DATABASE_URL" \
  --dry-run
```

Load approved rows:

```bash
python scripts/load_manifest.py \
  manifest/documentation_manifest_template.csv \
  --dsn "$DATABASE_URL"
```

For tenant-specific company policies, first create tenant-specific `kb.source` rows such as `COMPANY_POLICY` and `COMPANY_PROCEDURE`, then load `company_document_manifest_template.csv` with `--tenant-code`. The optional demo bootstrap creates sample tenant sources.

## Oracle documentation acquisition control

The manifest intentionally seeds Oracle rows with:

```text
acquisition_permission = PENDING
acquisition_method     = MANUAL_UPLOAD
```

Do not change them to automated direct download until your organization has recorded the necessary permission or contractual basis.

The acquisition script:

- Downloads only explicit URLs already stored in the manifest
- Does not crawl or discover links
- Selects only `APPROVED_DIRECT_DOWNLOAD` entries marked `APPROVED`
- Blocks Oracle-hosted URLs unless a permission reference exists in both the database row and command line
- Applies a configurable delay
- Records an ingestion run, per-document outcome and SHA-256 checksum

Example after approval:

```bash
python scripts/acquire_approved_documents.py \
  --dsn "$DATABASE_URL" \
  --output-dir /secure/knowledge/oracle \
  --oracle-permission-reference "LEGAL-APPROVAL-12345" \
  --delay-seconds 3
```

A production implementation should replace the local output directory with an object-storage adapter and secrets-managed configuration.

## Register manually supplied files

After a manifest row is approved and its `local_file_path` points to an existing file, register the original file and checksum as a versioned knowledge document:

```bash
python scripts/register_local_documents.py \
  --dsn "$DATABASE_URL" \
  --tenant-code DEMO
```

This creates the `kb.document` and `kb.document_version` records and leaves extraction, validation and publication pending. Unchanged files are detected by SHA-256 and recorded as `SKIPPED_UNCHANGED`.


## Ingestion state model

Manifest entries flow through these item states:

```text
QUEUED
  -> ACQUIRING
  -> ACQUIRED
  -> EXTRACTING
  -> EXTRACTED
  -> CHUNKING
  -> CHUNKED
  -> EMBEDDING
  -> EMBEDDED
  -> VALIDATING
  -> PUBLISHED
```

Alternative terminal states are:

```text
SKIPPED_UNCHANGED
BLOCKED_PERMISSION
FAILED
```

Only documents with an approved document record, a current version and a passed/warning validation state appear in `kb.v_active_document_chunk`.

## Retrieval

`kb.search_chunks_1536` demonstrates hybrid retrieval using:

- PostgreSQL full-text ranking
- pgvector cosine similarity
- Release filters
- Audience filters
- Security-classification filters
- Source-type weighting

The function is a starting point. Production retrieval should additionally enforce `kb.document_permission` against the authenticated user’s roles, support groups and business unit before sending evidence to an LLM.

## Application services still required

This package establishes the physical data model. The following are application/worker responsibilities and are not fully implemented in SQL:

- JSON rule evaluation for routing and queues
- Atomic workflow-transition service with validators and actions
- Business-calendar arithmetic and SLA clock workers
- Approval-notification and decision orchestration
- Document parsing, semantic chunking and embedding generation
- Object-storage upload and malware scanning
- Email/chat integrations
- LLM orchestration and guardrails
- Document ACL evaluation
- CDC or ETL into an OAC dimensional reporting model

The email gateway, retention executor, configuration publication workflow, AI budget dashboard, model calls, and full CMDB are also intentionally deferred. See `docs/PRODUCT_BACKLOG.md` and `docs/architecture/postgresql-baseline-assessment.md`.

A recommended next implementation layer is a FastAPI service with modules for identity context, tickets, workflows, routing, SLAs, knowledge ingestion, retrieval and AI tools.

## Operational cautions

- Use a migration tool such as Alembic or Flyway after the initial baseline.
- Do not grant the application direct update access to immutable audit/event tables.
- Execute ticket transitions through a service layer rather than direct table updates.
- Keep original Oracle and company documents unchanged in object storage.
- Preserve canonical source URLs, checksums, copyright notices and approval references.
- Separate employee, analyst and technical-specialist retrieval collections.
