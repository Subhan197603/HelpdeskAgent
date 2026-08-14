# Analyst queues and activity timeline

Milestone 4, Task 4.3 provides versioned saved queues and an immutable activity timeline. Queue
definitions are configuration: they select tickets but never own or copy them. Only effective
`PUBLISHED` queue versions execute, and overlapping published versions fail closed.

## Queue APIs

```http
GET /api/v1/agent/queues
GET /api/v1/agent/queues/{queue_id}/tickets?limit=50&cursor=...
```

The development configuration publishes Unassigned, Assigned to me, Fusion AP group, and ERP
project queues. `GROUP` queues require membership in their configured owner group. Every ticket
query independently enforces tenant and assignment-aware visibility, even for a visible queue;
project and platform administrators retain their existing read-all authority.

Queue filters use a restricted JSON expression language compiled only through a fixed field and
operator allowlist. SQL identifiers and fragments never come from configuration or request data.
Optional status, priority, support-group, current-assignee, and search filters are parameterized.
Non-admin callers may filter only by one of their own support groups. Search uses
`plainto_tsquery('simple', ...)` over ticket key and summary, not raw SQL or regular expressions.

Results sort by `created_at DESC, ticket_id DESC`. The opaque cursor contains both stable keys and
a hash of the queue plus active request filters; using it with another queue or filter set returns
`422`. Responses include assignment, reporter, timestamps, and available first-response and
resolution SLA targets. Migration `0007_queue_performance_indexes` adds reversible indexes for
unassigned, assignee, group, project, and full-text queue access paths.

## Personal saved ticket filters

Milestone 12 Task 12.1 adds private presets over those existing queue inputs:

```http
GET    /api/v1/agent/saved-filters
POST   /api/v1/agent/saved-filters
GET    /api/v1/agent/saved-filters/{saved_filter_id}
PATCH  /api/v1/agent/saved-filters/{saved_filter_id}
DELETE /api/v1/agent/saved-filters/{saved_filter_id}
PUT    /api/v1/agent/saved-filters/order
GET    /api/v1/agent/saved-filters/{saved_filter_id}/tickets
```

Each record is derived from the authenticated tenant and user. Repository predicates and row-level
security both enforce that owner boundary, and inaccessible records return not found. A preset can
contain only a published base queue plus status, priority, bounded plain-text search, support group,
and `me` or `unassigned` assignee values. Applying one delegates to the ordinary queue query, so
current queue visibility, support-group scope, ticket visibility, stable pagination, and
parameterization are rechecked rather than stored as authority.

Create requires `Idempotency-Key`. Update, reorder, and delete use `row_version` for optimistic
concurrency; update and delete also accept matching `If-Match`. Names are unique per tenant and
owner, case-insensitively. The analyst UI keeps unsaved filters in the URL, identifies an applied
preset with `savedFilter`, and returns to ordinary query state when a preset is edited. Saved
filters never store SQL, regular expressions, queue expressions, sort definitions, shared scope,
or ticket mutations.

## Personal canned responses

Milestone 12 Task 12.2 adds private, bounded plaintext response snippets:

```http
GET    /api/v1/agent/canned-responses
POST   /api/v1/agent/canned-responses
GET    /api/v1/agent/canned-responses/{canned_response_id}
PATCH  /api/v1/agent/canned-responses/{canned_response_id}
DELETE /api/v1/agent/canned-responses/{canned_response_id}
PUT    /api/v1/agent/canned-responses/order
```

Tenant and owner identity are derived from the authenticated analyst and are
enforced by repository predicates and row-level security. Create is
idempotent; update, reorder, and delete use optimistic row versions. Selecting
a snippet inserts only editable text into the existing browser draft. It does
not change public/internal visibility, invoke AI, or post a comment. The
existing authorized comment endpoint remains the sole posting path. Snippet
bodies must not enter logs, metrics, audit summaries, or error details. Shared,
administrator-managed, executable, and variable-substitution templates are
not supported.

## Personal ticket watchlists

Milestone 12 Task 12.3 adds private ticket-watch preferences:

```http
GET    /api/v1/agent/watched-tickets?limit=50&cursor=...
PUT    /api/v1/agent/tickets/{ticket_key}/watch
DELETE /api/v1/agent/tickets/{ticket_key}/watch
```

Watch and unwatch are idempotent. Tenant and owner identity come only from the
authenticated analyst, and both repository predicates and row-level security
enforce that boundary. The personal list is ordered by the time watched plus a
stable identifier and uses an opaque keyset cursor.

Every operation rechecks ordinary analyst ticket visibility. If group access
changes, the stored preference is retained but the ticket is omitted from the
list and cannot be followed or removed until access is restored. A watch never
creates a participant, changes assignment, grants access, emits a ticket event
or outbox fact, or creates notification or queue-subscription behavior.

## Accessible keyboard accelerators

Milestone 12 Task 12.4 adds a small analyst-only shortcut set over existing,
authorized UI routes and controls:

- `G` then `D`, `Q`, or `K` navigates to the dashboard, queues, or analyst
  knowledge respectively; unavailable destinations remain unavailable.
- `/` focuses the visible queue or knowledge search field.
- `F` focuses the visible personal saved-filter or canned-response selector.
- `J` and `K` move focus between visible queue or watchlist rows without
  opening or changing a ticket.
- `?` opens the shortcut reference, and `Escape` cancels a pending sequence or
  closes the reference and restores focus.

Shortcuts pause in inputs, textareas, selects, editable content, and while
another modal is active. Modifier combinations, key repeat, and input-method
composition are not intercepted. The accelerators never post comments, alter
workflow or assignment, watch or unwatch tickets, delete data, bypass a
permission check, or skip a confirmation.

## Activity and comments

```http
GET /api/v1/tickets/{ticket_key}/timeline
GET /api/v1/agent/tickets/{ticket_key}/timeline
POST /api/v1/agent/tickets/{ticket_key}/comments
```

Timeline items are derived from append-only `ticket_event` and `ticket_comment` records and are
classified as `PUBLIC`, `INTERNAL`, or `SYSTEM`. Customer timelines apply a database-side public
classification predicate and expose only public-safe ticket events and public comments. Analyst
timelines require assignment-aware ticket visibility and may include internal/system activity.
AI-generated comments are excluded until a future approved review-and-publication workflow exists.

Analysts can create public comments or internal notes. The endpoint requires analyst access plus
the visibility-specific permission, validates ticket scope, and requires `Idempotency-Key`.
Successful commands atomically write the immutable comment, matching ticket event, audit record,
and idempotency result. Comment bodies are not copied into audit data.

## Portal behavior and limits

The analyst workspace lists authorized queues, supports safe search and cursor navigation, and
shows assignment-aware empty, loading, and error states. Ticket activity identifies its
classification, and analysts explicitly choose public or internal visibility before posting.
Employees receive only the public timeline.

The initial implementation supports the four Task 4.3 queue categories. Administrative queue
editing, arbitrary sort shapes, SLA-derived queues, live counts, bulk actions, and background
subscriptions remain deferred. Timeline responses are capped at 500 immutable items pending a
future timeline-pagination requirement.
