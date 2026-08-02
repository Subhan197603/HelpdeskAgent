# Approval operations

Milestone 5, Task 5.2 provides a transactional approval foundation. It does not
send email or in-application notifications; it only emits outbox facts for the
notification task to consume later.

## Supported definitions

Runtime execution accepts effective published versions in these modes:

- `ANY_ONE_APPROVER` with an explicit `user_ids` array
- `ALL_APPROVERS` with an explicit `user_ids` array
- `MANAGER_APPROVAL` with subject `REQUESTED_FOR_OR_REPORTER`

Other baseline modes fail closed. Every resolved user must be active and belong
to the ticket tenant. Requester self-approval defaults to false and can only be
enabled on the captured immutable definition version. A definition may require
a rejection comment and may set `expires_after_minutes`.

## Runtime behavior

A workflow `CREATE_APPROVAL` action creates one pending approval, pins its
definition version, resolves its approvers, writes ticket/audit events, and
adds an `APPROVAL_REQUESTED` outbox fact in the transition transaction.

Assigned approvers use `GET /api/v1/my/approvals`. Decisions use
`POST /api/v1/approvals/{approval_id}/decisions`, an `Idempotency-Key`, and an
`expected_version` (optionally mirrored by `If-Match`). Each approver decision
is append-only and unique. The approval row uses optimistic concurrency.

Terminal outcomes execute only a definition-pinned transition marked
`APPROVAL_CONTINUATION`; analysts cannot call those transitions directly.
Expired instances reject decisions and persist the `EXPIRED` state. Explicit
workflow resets can call the internal cancellation operation, which persists
`CANCELLED`. Both operations produce audit and outbox facts.

## Security checks

API permission is necessary but not sufficient: queries always require the
authenticated user to be an assigned approver. Tenant predicates are present
on every runtime query. When optional RLS is enabled, Task 5.2 enables matching
tenant policies on approver assignments and immutable decisions.
