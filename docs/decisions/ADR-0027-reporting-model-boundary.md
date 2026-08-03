# ADR-0027: Tenant-safe reporting schema and reporting-role boundary

- Status: Accepted
- Date: 2026-08-03

## Context

Task 10.1 needs an OAC-consumable reporting model over tickets, SLAs, approvals, knowledge, and
AI usage. The physical baseline granted `helpdesk_reporting` SELECT on every operational table,
which exposes free-text ticket content, comments, and user contact data to any reporting
consumer and violates the no-unrestricted-operational-access requirement.

## Decision

Migration `0020_reporting_views` creates a dedicated `reporting` schema of plain views owned by
the migration owner. Views execute with owner privileges, so `helpdesk_reporting` needs — and now
has — access only to `reporting`: the migration revokes the role's schema USAGE and table SELECT
grants on all operational schemas and grants USAGE plus SELECT on the reporting views instead.
The physical baseline files stay untouched; the re-scoping is a normal post-baseline Alembic
change with a full downgrade that restores the previous grants.

The model exposes conformed dimensions (`dim_service_project`, `dim_support_group`,
`dim_request_type`, `dim_workflow_status`, `dim_priority`) and fact views (`fact_ticket`,
`fact_ticket_sla`, `fact_approval`, `fact_knowledge_document`, `fact_ai_usage`,
`fact_ai_feedback`) plus an append-only `feed_ticket_events` change feed. Every fact carries
`tenant_id` and an `extraction_watermark` column; all temporal columns are `timestamptz` (UTC).
Business-time measures come from the SLA engine's persisted `elapsed_working_seconds` and
`accumulated_pause_seconds` rather than being recomputed in reporting.

No personal data crosses the boundary: no user identifiers beyond none at all in facts, no
names, no email addresses, and no free-text (summaries, descriptions, comments, feedback text)
are exposed. Incremental extraction uses `feed_ticket_events.event_id` (monotonic identity) or a
fact's `extraction_watermark`; a new `itsm.ticket_event(tenant_id, event_id)` index supports
tenant-scoped incremental scans.

## Consequences

- OAC connects as a login member of `helpdesk_reporting` and can see only the reporting schema;
  a compromised reporting credential cannot read ticket bodies, comments, or user records.
- Reporting content changes are versioned migrations with reconciliation tests comparing view
  counts and sums against source transactions.
- Analytics needing user- or text-level detail require a separately approved model change; the
  default boundary is PII-free.
- The employee/analyst applications are unaffected; no runtime code path uses the reporting
  schema.
