# Deterministic routing and assignment

Milestone 4, Task 4.2 assigns tickets from immutable, published routing-rule versions. The
service does not call an LLM and does not accept a client-selected rule, version, group, or
analyst for automatic routing.

## Routing command

Support managers, project administrators, and platform administrators hold the stable
`TICKET_ROUTE` permission. The endpoint is tenant scoped and support managers may route
only unassigned tickets or tickets visible to one of their groups.

```http
POST /api/v1/agent/tickets/{ticket_key}/route
Idempotency-Key: example-routing-key
If-Match: "1"
Content-Type: application/json

{"row_version":1}
```

The service locks the ticket and verifies its optimistic row version. It loads effective
`PUBLISHED` versions belonging to active rules for the ticket's tenant and project. More
than one effective published version for a base rule fails closed.

Non-default rules are ordered by:

1. ascending configured rule priority;
2. descending predicate specificity;
3. most recent effective start;
4. stable routing-rule-version UUID.

Administrators reserve lower numeric priority bands for emergency and security rules, so
their precedence is explicit configuration subject to the same published-version controls;
there is no hidden or AI-driven override.

The first matching rule wins. Each project must have exactly one effective rule whose
condition is empty; that rule is the explicit default and is used only when no conditional
rule matches. Missing or multiple defaults are configuration conflicts.

The restricted data-only evaluator supports project, service, module, application
environment, work type, priority, current ticket fields, and `field.<custom_field_code>`
predicates. Unknown fields, operators, executable expressions, templates, SQL, and malformed
configuration fail closed. AI classification is not used for rule selection.

`GROUP_ONLY` and `ROUND_ROBIN` are implemented. Round robin serializes selection with a
transaction-scoped PostgreSQL advisory lock keyed to the support group, then selects the
eligible active member with the fewest historical assignments and a stable user-ID
tie-breaker. `NAMED_ASSIGNEE` is accepted only when the configured user is an active member
of the configured tenant group. Other assignment methods remain deferred.

## Manual reassignment

Manual reassignment requires the separate `TICKET_ASSIGN_MANUAL` permission, held by support
managers and project/platform administrators.

```http
POST /api/v1/agent/tickets/{ticket_key}/assignment
Idempotency-Key: example-manual-assignment
Content-Type: application/json

{"assignment_group_id":"23000000-0000-0000-0000-000000000001","assignee_user_id":"22000000-0000-0000-0000-000000000003","reason":"Manager triage escalation","row_version":2}
```

The group must be active in the ticket tenant. An optional analyst must be an active user
and active member of that group. Client-provided tenant, role, rule, and routing-version
values are never accepted.

## History, audit, and downstream work

Every successful automatic or manual assignment commits atomically with:

- an immutable `assignment_history` row containing old/new group and analyst values;
- both `routing_rule_id` and `routing_rule_version_id` for automatic routing;
- `TICKET_ROUTED` or `TICKET_REASSIGNED` ticket events;
- an immutable audit event containing correlation and request identifiers; and
- a `TICKET_ASSIGNED` transactional outbox event.

The routing event and audit payload retain the ordered rule-version evaluations, the matched
version, safe structured dimensions, custom-field codes, and a SHA-256 hash of the complete
deterministic input. Classifier version and confidence are explicitly null and the source is
`CONFIGURATION_ONLY`; summaries, descriptions, and custom-field values are not copied into
the audit trace.

Commands require `Idempotency-Key`. The durable request hash includes the ticket, expected
row version, and all assignment inputs. Identical retries return the existing result with
`Idempotent-Replayed: true`; key reuse with different inputs or principals returns `409`.
Ticket row locking and guarded updates give concurrent commands one winner and one `409`.

No queue UI, queue engine, background outbox consumer, SLA calculation, or AI-based routing
is included. No Alembic migration is required because the adopted baseline already provides
routing versions, assignment history version references, idempotency, audit, and outbox
storage. The development fixtures add an Accounts Payable route and an explicit ERP default.
