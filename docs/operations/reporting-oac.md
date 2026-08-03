# OAC reporting model

Milestone 10, Task 10.1 publishes a tenant-safe reporting schema for Oracle Analytics Cloud (or
any SQL-capable BI tool). All objects live in the PostgreSQL `reporting` schema and are the only
objects the `helpdesk_reporting` role can read.

## Connection

Create a login role that is a member of `helpdesk_reporting` (deployment-managed credentials;
never stored in the repository) and register it in OAC as a PostgreSQL connection. The role has:

- `USAGE` on schema `reporting` and `SELECT` on its views — nothing else;
- no access to `identity`, `config`, `itsm`, `kb`, `ai`, `audit`, or `integration`;
- no INSERT/UPDATE/DELETE anywhere.

## Subject areas

| View                                | Grain                   | Key measures / attributes                                                                                    |
| ----------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------ |
| `reporting.dim_service_project`     | project                 | key, name, active flag                                                                                       |
| `reporting.dim_support_group`       | support group           | code, name, active flag                                                                                      |
| `reporting.dim_request_type`        | request type            | code, name, work-type code                                                                                   |
| `reporting.dim_workflow_status`     | workflow status version | code, name, category, terminal flag                                                                          |
| `reporting.dim_priority`            | priority                | code, name, rank order                                                                                       |
| `reporting.fact_ticket`             | ticket                  | status, priority, group, channel, environment, resolution, created/first-response/resolved/closed timestamps |
| `reporting.fact_ticket_sla`         | SLA instance            | state, started/target/completed/breached, elapsed working seconds, pause seconds                             |
| `reporting.fact_approval`           | approval instance       | status, requested/completed, approver and decision counts                                                    |
| `reporting.fact_knowledge_document` | document version        | source type, release, extraction/validation status, approval status                                          |
| `reporting.fact_ai_usage`           | usage-ledger entry      | provider/model alias, use case, tokens, estimated cost                                                       |
| `reporting.fact_ai_feedback`        | feedback decision       | decision code, reason code, conversation type                                                                |
| `reporting.feed_ticket_events`      | ticket event            | event type, actor type, created timestamp                                                                    |

All facts include `tenant_id`; always add a tenant filter (or dedicated per-tenant connection) in
multi-tenant deployments. All timestamps are UTC `timestamptz`. Convert to business timezones in
the analytics layer only. Business-time SLA measures come from persisted engine values
(`elapsed_working_seconds`, `accumulated_pause_seconds`); do not recompute business time in BI.

## Incremental extraction

- `feed_ticket_events.event_id` is a monotonic bigint. Persist the highest extracted `event_id`
  and pull `WHERE event_id > :watermark ORDER BY event_id` for change tracking. A
  `(tenant_id, event_id)` index supports tenant-scoped pulls.
- Every fact exposes `extraction_watermark` (`timestamptz`): pull
  `WHERE extraction_watermark > :last_run` for incremental refresh; do a periodic full refresh to
  pick up hard deletions (rare — most history is append-only).

## Privacy boundary

Views expose no user names, no email addresses, no user identifiers in facts, and no free text
(summaries, descriptions, comments, resolution text, feedback comments). Reconciliation and
column-shape tests in `tests/integration/test_reporting.py` enforce this; extending the model
with any personal data requires a reviewed migration and an ADR update (see ADR-0027).

## Dashboard specifications

Initial dashboards to build in OAC against these subject areas:

1. **Ticket operations** — created vs resolved trend (fact_ticket by created_at/resolved_at),
   open backlog by status category and priority, volume by project/request type/channel,
   AI-created share (`ai_created_flag`).
2. **SLA performance** — breach rate and met rate by priority and group
   (fact_ticket_sla.state_code), average elapsed working time, upcoming targets
   (`state_code='RUNNING' AND target_at < now() + interval '4 hours'`).
3. **Approvals** — pending age from requested_at, decision throughput, approval status mix.
4. **Knowledge health** — published/current versions by source type and release, validation
   failures, acquisition volume over time.
5. **AI usage and outcomes** — tokens and estimated cost by provider/model/use case
   (fact_ai_usage), copilot feedback mix and rejection reasons (fact_ai_feedback), usage trend
   against budget.

Reconciliation: each dashboard's headline counts must match the reconciliation queries in the
integration test suite (view counts equal source-table counts).
