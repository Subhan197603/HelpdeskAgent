# Deterministic workflow transitions

Milestone 4, Task 4.1 executes analyst ticket transitions from the exact workflow version
captured when the ticket was submitted. Runtime execution never resolves a newer workflow
version and accepts only captured `PUBLISHED` or `RETIRED` versions. PostgreSQL protects
published and retired configuration from mutation.

## Authorization and API

`AGENT`, `SUPPORT_MANAGER`, `PROJECT_ADMIN`, and `PLATFORM_ADMIN` roles receive the stable
`TICKET_TRANSITION` permission. Group-scoped roles may operate on unassigned tickets or
tickets assigned to one of their support groups; project and platform administrators use
their existing all-ticket scope. Tenant boundaries are always applied. Customers are denied.

```http
GET /api/v1/agent/tickets/{ticket_key}/transitions
```

The response reports the current status and row version plus active, guard-satisfied
transitions whose `from_status_id` matches the ticket's current status.

```http
POST /api/v1/agent/tickets/{ticket_key}/transitions
Idempotency-Key: example-idempotency-key
If-Match: "2"
Content-Type: application/json

{"transition_code":"RESOLVE","row_version":2,"field_updates":{"resolution_code":"FIXED","resolution_summary":"Configuration corrected."},"comment":"The issue is resolved."}
```

The optional `If-Match` value must agree with the body. A stale row version, concurrent
winner, invalid transition, or failed guard returns RFC 7807 `409`; missing required fields
return a structured `422`. Unknown resources remain `404` to avoid scope disclosure.

## Deterministic execution

The service locks the ticket, checks its expected row version and captured version, resolves
one active transition from its current status, evaluates its guard and validators, applies
allowlisted field and timestamp actions, updates the status, and commits all effects in one
transaction. Transition endpoints currently accept only `resolution_code` and
`resolution_summary` as caller field updates. Stored actions are restricted to
`SET_TIMESTAMP`, `CLEAR_FIELD`, and allowlisted `SET_FIELD` operations.

Guards are data-only JSON objects composed from `all`/`any` groups and the documented
comparison operators. Unknown properties, operators, validators, action types, executable
code, templates, SQL, and LLM decisions fail closed as workflow configuration conflicts.

Each success creates:

- the baseline trigger's append-only `STATUS_CHANGED` history record;
- an append-only `WORKFLOW_TRANSITION_EXECUTED` event containing the captured workflow
  version, transition, states, row versions, and request correlation;
- one `TICKET_WORKFLOW_TRANSITIONED` transactional outbox record for downstream routing,
  SLA, and notification consumers; and
- one immutable audit event.

No routing or SLA calculation occurs in this service. Optional public comments are written
in the same transaction using the existing audited comment boundary.

## Idempotency and concurrency

The SHA-256 request fingerprint covers the tenant-scoped ticket key, transition, expected
version, field updates, and normalized comment. The unique idempotency record is locked in
the transaction. An identical retry returns the current ticket with
`Idempotent-Replayed: true`; a changed request or principal returns `409`. PostgreSQL row
locking plus the guarded update ensures two different commands using the same row version
produce one winner and one concurrency conflict.

No schema migration is present in Task 4.1: the adopted physical baseline already provides
the captured workflow version, optimistic row version, append-only ticket history, audit,
and outbox tables. Migration upgrade/downgrade testing is therefore not applicable. The
development catalogue fixture adds deterministic incident statuses and transitions without
changing the production baseline.
