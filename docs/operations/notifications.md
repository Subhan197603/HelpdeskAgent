# Notification operations

Task 5.3 delivers email and in-app notifications from dedicated transactional
outbox facts. Internal comments are never notification inputs.

## Templates and recipients

Each event selects an effective published tenant template for `EMAIL` and
`PORTAL`, preferring tenant configuration over global configuration. The exact
version is stored with the resulting delivery. Supported variables are:

- `ticket_key`
- `recipient_name`
- `event_name`
- `status_name`
- `action_url`

Unknown, malformed, executable, and triple-brace syntax fails permanently.
HTML values are escaped. The initial templates intentionally omit summaries,
descriptions, comments, and internal notes.

Ticket events resolve an active tenant user from server-owned ticket state.
Approval requests resolve their pending assigned approvers. Assignment,
customer-comment, and SLA events target the assigned analyst. Customer-facing
events target the requested-for user or reporter. Group-only routing does not
create a user notification until a concrete assignee exists. The event actor is
excluded where applicable.

## Delivery

Configure the worker with `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, optional paired
`SMTP_USERNAME`/`SMTP_PASSWORD`, `SMTP_STARTTLS`, and
`SMTP_MESSAGE_ID_DOMAIN`. Production rejects Mailpit/localhost SMTP and requires
STARTTLS.

The planner and sender both use `FOR UPDATE SKIP LOCKED`. Planning is protected
by database uniqueness. Email delivery records use a deterministic Message-ID,
append-only attempt rows, exponential retry with bounded jitter, a maximum
attempt count, and final-failure state. Logs contain identifiers and error class
names only—not recipients, subjects, or bodies.

Users list their own inbox through `GET /api/v1/my/notifications` and mark an
item read through `POST /api/v1/my/notifications/{id}/read`. Both operations are
tenant- and user-scoped.
