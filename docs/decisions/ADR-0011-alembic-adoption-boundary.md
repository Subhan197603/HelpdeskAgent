# ADR-0011: Alembic adoption boundary

- Status: Accepted
- Date: 2026-08-01

## Context

The approved PostgreSQL package is an externally installed, multi-schema physical baseline. The
application has no complete ORM representation of it, while all later database changes require
transactional migration history, deployment serialization, and destructive-change review.

## Decision

- Store Alembic state in `config.alembic_version`, because `config` is an approved baseline schema
  and migration configuration belongs there.
- Represent the external installation with the empty `0000_physical_baseline` revision. Validated
  project tooling must confirm package checksums and database objects before stamping it.
- Serialize online Alembic commands with PostgreSQL session advisory lock key
  `6817315412136801249` and a bounded timeout.
- Treat SQLAlchemy metadata as application-managed partial metadata. Reflected baseline tables
  without corresponding managed metadata are excluded from autogeneration, and autogeneration is
  disabled while the managed metadata set is empty.
- Require explicit revisions for changes not yet represented by application metadata. A static
  migration guard rejects destructive or rewrite-sensitive operations unless the revision cites a
  dedicated ADR that names the revision.

## Alternatives

Rebuilding the baseline as Alembic revisions, storing the version table in `public`, allowing
empty metadata to autogenerate drops, and using Redis for deployment locking were rejected.

## Consequences

Brand-new databases require baseline installation, validation, and stamping before upgrades.
Migration login roles need inherited owner permissions for approved schemas. Administrators can
technically bypass project validation with raw Alembic commands, so deployment automation must use
the documented project commands. Future ORM modules are adopted incrementally without claiming
ownership of every baseline table.
