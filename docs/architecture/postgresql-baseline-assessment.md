# PostgreSQL baseline impact assessment

## Status

Implemented for Milestone 0, Task 0.2 before the first physical baseline installation.

`BUILD_SPEC.md` is authoritative. The production architecture addendum was used as supporting governance guidance.

## Starter capabilities retained

- Seven domain schemas: `identity`, `config`, `itsm`, `kb`, `ai`, `audit`, and `integration`
- PostgreSQL extensions `pgcrypto`, `pg_trgm`, `unaccent`, and `vector`
- UUID aggregate keys and time-friendly identity keys for high-volume events
- Core ticket, workflow, routing, queue, SLA, approval, knowledge, AI, audit, and outbox structures
- Explicit Oracle Fusion Applications `26C` and Fusion Data Intelligence `26.R2` knowledge-release families
- Optional demo configuration and ticket scripts outside the normal installer
- Error-stopping modular installation

## Foundational corrections incorporated

- Domain-specific immutable versions for request forms, workflows, routing, queues, calendars, SLAs, approvals, notifications, prompts, tool sets, model policies, retrieval, embedding, and agent configuration
- Runtime references placed on the records that consume configuration versions
- Concurrency-safe API idempotency records
- Operational application, environment, product-release, assignment-history, and diagnostic-endpoint registry
- Deterministic impact, urgency, priority, and effective-dated priority matrix
- Email mailbox, normalized message/recipient metadata, and ticket communication correlation
- Retention policies, assignments, and separate legal-hold resources
- Attachment quarantine, scan, release, encryption-status, retention, classification, and deletion metadata
- Database-controlled AI kill switch, limits, budgets, provider/model aliases, and immutable usage ledger
- General append-only audit events and immutable approval decisions
- Effective-dated ownership assignments on the existing `config.service_node` hierarchy
- Owner, migrator, application, worker, reporting, and read-only group roles with explicit immutable-history restrictions

## Deferred application behavior

The baseline defines enforceable storage contracts only. It does not implement configuration publication services, priority evaluation, ticket mutation APIs, email connectivity, retention execution, malware scanning, object transfer, AI calls, usage aggregation jobs, document ingestion, or service-ownership consumers. Those capabilities remain assigned to later milestones in `docs/PRODUCT_BACKLOG.md`.

## Migration boundary

The modular SQL installer is the physical baseline and is intentionally unsupported as a repeatable production migration. Task 1.2 will create an empty Alembic marker revision named `0000_physical_baseline` for databases that already contain this baseline. Every subsequent schema change must use reviewed Alembic migrations. The baseline installer must never be rerun as a production migration.
