# ADR-0013: Versioned SLA Runtime State

## Status

Accepted for Milestone 5, Task 5.1.

## Context

The physical baseline contains versioned business calendars, SLA definitions and goals, plus
runtime ticket SLA tables. The runtime state constraint predates the complete SLA lifecycle and
does not include `PENDING`; SLA events also lack a stable idempotency key. Published calendar
versions can currently be changed indirectly through their working-period and exception rows.

## Decision

Revision `0009_business_calendar_sla` may replace the existing `ticket_sla_state_ck` and
`ticket_sla_event_type_ck` constraints with strictly wider constraints. This is a reviewed
constraint replacement with no data deletion or value rewrite.

The revision will also:

- add stable runtime event keys and persisted warning/version fields;
- protect the child rows of published or retired calendar versions;
- add uniqueness and due-work indexes for idempotent workers; and
- grant the non-login worker role only the SLA mutations it requires.

SLA runtime rows retain the exact SLA goal and business-calendar versions used. Configuration
history remains immutable, while SLA lifecycle events remain append-only.

## Consequences

Workers can safely retry lifecycle events and periodic warning/breach scans. Downgrade restores
the original constraints after removing only Alembic-owned Task 5.1 fields and indexes. A
downgrade is rejected by PostgreSQL if post-upgrade data uses a lifecycle value the earlier
schema cannot represent; operators must resolve such runtime data explicitly rather than lose it.
