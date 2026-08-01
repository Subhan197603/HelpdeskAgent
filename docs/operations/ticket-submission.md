# Ticket draft and submission foundation

Milestone 3, Task 3.2 keeps editable drafts separate from permanent tickets. Creating a
draft has no permanent ticket side effect; only `POST /api/v1/ticket-drafts/{id}/submit`
allocates a project key and creates a ticket.

## Configuration and validation

A draft binds the effective published `request_type_version_id` at creation. Submission
reuses that exact immutable form and never upgrades it silently. Existing drafts may use a
`RETIRED` version because retirement is an availability decision, while any other state is
rejected as a configuration conflict. Published form components remain database-immutable.

The backend rejects unknown and duplicate fields, validates required values, lengths,
numeric ranges, ISO dates/timestamps, active select options, UUID references, and the
restricted data-only conditional language. Text whitespace, numbers, booleans, timestamps,
and unordered multi-select values are normalized. No executable expressions are accepted.

Impact and urgency are caller inputs. The service resolves one effective approved matrix
row by service, project, tenant, then global specificity and evaluation order. Missing or
equally ranked rows fail closed. The resolved priority and matrix identifier are retained on
both the draft and ticket; there is no priority override in this milestone.

## Concurrency and confirmation

Draft updates carry `row_version`; `If-Match` may also be supplied and cancellation requires
it. A stale version returns RFC 7807 `409`. Validation moves a draft to
`READY_FOR_REVIEW`; edits return it to `DRAFT`. A submitted draft is protected by a database
trigger and cannot be changed or physically deleted by the runtime role.

Submission requires `Idempotency-Key`. Its SHA-256 request fingerprint covers the draft and
confirmed row version. The unique tenant/operation/key record is locked in the submission
transaction: an identical retry returns the original ticket, while a changed request or
principal returns `409`. A failed transaction rolls back its in-progress claim, draft state,
counter update, ticket, custom values, history, and outbox records together, so it is
immediately retryable.

The existing ticket-key trigger locks and increments `itsm.project_ticket_counter`; it never
uses `MAX()+1`. Its migration-applied security-definer boundary lets the trigger update the
protected counter without granting the API arbitrary counter access. Transaction rollback
also rolls back the allocated number, so this strategy does not intentionally create gaps.

The permanent ticket captures the exact request-form version, one effective published
workflow version, its single initial status, and the priority matrix. Normalized custom
values use the baseline typed columns. The baseline trigger appends the immutable
`TICKET_CREATED` event. Three stable `PENDING` outbox records (`ROUTE_TICKET`, `START_SLA`,
and `NOTIFY_TICKET_CREATED`) are written in the same transaction; consumers and their
business behavior remain deferred.

## API examples

```http
POST /api/v1/ticket-drafts
X-Developer-User: DEV/customer
Content-Type: application/json

{"request_type_id":"33000000-0000-0000-0000-000000000001","summary":"Invoice error","description":"Invoice validation fails repeatedly.","impact":"LIMITED","urgency":"NORMAL","custom_fields":[{"field_code":"environment","value":"PROD"}]}
```

```http
POST /api/v1/ticket-drafts/{draft_id}/submit
Idempotency-Key: portal-confirm-018f
If-Match: "2"
Content-Type: application/json

{"row_version":2}
```

Other endpoints are `GET` and `PATCH /api/v1/ticket-drafts/{id}`,
`POST /api/v1/ticket-drafts/{id}/validate`, `DELETE /api/v1/ticket-drafts/{id}`,
`GET /api/v1/tickets/{ticket_key}`, and cursor-paginated `GET /api/v1/my/tickets`.
Customer responses expose only reporter/requested-for-safe ticket and creation-history data.

## Development and verification

`database/development/catalogue.sql` provides synthetic basic incident, Oracle Fusion
error, access request, and reporting forms plus an initial workflow status. It is not part of
the production baseline. Tests build isolated databases and load their own fixtures.

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -m "not integration"
uv run pytest tests/integration/test_tickets.py -m integration
uv run python -m apps.api.app.openapi
```

Known limitations are intentional: requested-for-other is restricted to the platform-admin
permission, expiry has no cleanup worker, event consumers are absent, and routing, SLA
execution, notifications, attachments, internal comments, and later workflow transitions are
deferred. Task 3.3 adds tenant-safe analyst reads and public comments only.
