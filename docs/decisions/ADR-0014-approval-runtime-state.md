# ADR-0014: Approval runtime state

## Status

Accepted for Milestone 5, Task 5.2.

Approved migration: 0010_approval_engine

## Decision

Approval instances retain the exact published `approval_definition_version_id`
selected when they are created. Runtime instances use a positive `row_version`
for optimistic concurrency and an optional absolute expiry time. Approver rows
carry the tenant identifier so both assignments and immutable decisions can be
protected by tenant RLS when the optional RLS package is enabled.

Each assigned approver may create at most one append-only decision for an
approval instance. The mutable assignment row is only a projection of that
decision. A partial unique index prevents more than one pending instance for the
same ticket and definition.

The first supported modes are `ANY_ONE_APPROVER`, `ALL_APPROVERS`, and
`MANAGER_APPROVAL`. Unsupported published modes fail closed. Requester
self-approval is denied unless the immutable definition version explicitly opts
in.

## Consequences

Approval decisions can safely drive workflow continuation in the same database
transaction, are replay-safe through the existing idempotency store, and retain
the configuration used for later audit. Notification delivery remains outside
this task; only transactional outbox facts are emitted.
