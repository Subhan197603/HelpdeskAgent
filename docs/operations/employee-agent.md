# Employee helpdesk agent

Milestone 8, Tasks 8.2 and 8.3 provide an employee-authorized, retrieval-first conversation API
with explicit resolution feedback and confirmed ticket escalation. The assistant cannot submit a
ticket directly: unresolved feedback creates a draft through the deterministic ticket service, and
the employee must review, edit, validate, and explicitly confirm it.

## API

- `POST /api/v1/assistant/conversations` creates an owner-scoped conversation.
- `GET /api/v1/assistant/conversations/{conversation_id}` returns its current state to its owner.
- `POST /api/v1/assistant/conversations/{conversation_id}/messages` returns server-sent events.
- `POST /api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/cancel` cancels an
  active, owner-scoped turn.
- `POST /api/v1/assistant/conversations/{conversation_id}/resolution-feedback` records one
  idempotent helpful/not-helpful outcome. A resolved outcome closes the conversation without a
  ticket. An unresolved outcome requires exact catalogue/form/version identifiers and creates or
  returns the conversation's ticket draft.
- `POST /api/v1/assistant/conversations/{conversation_id}/confirm-ticket` requires an
  `Idempotency-Key` and the current draft row version. It submits only a previously validated draft
  and returns the backend-issued ticket key.

The stream emits `state`, `citation`, `delta`, and `done` events. A cancelled turn emits
`cancelled`. Clients must treat the server-provided turn identifier as opaque and must not combine
events from different turn identifiers. Reverse proxies must leave SSE buffering disabled.

## Safety behavior

The service searches employee-authorized, published evidence before asking the configured model
for a resolution. Low-confidence, absent, suspicious, or unavailable evidence produces a safe
ticket-workflow recommendation. Citations are constructed from retrieval metadata rather than
accepted from model output. Retrieved text and conversation text are treated as untrusted data,
prompt-injection-shaped evidence is excluded, prior context is filtered and bounded, and the model
receives no tools. Any unexpected tool request is refused.

Security-sensitive, payroll, financial-posting, privileged-access, major-outage, broad-impact, and
failed-prior-solution messages immediately recommend human escalation. AI-disabled,
provider-failure, circuit-breaker, timeout, and cancellation paths leave deterministic ticketing
available.

Escalation uses the existing ticket draft API and its catalogue/form/version, authorization,
validation, optimistic-locking, idempotency, priority-matrix, routing, workflow, audit, and outbox
controls. The model receives no ticket mutation tool and cannot set priority, routing, status,
permissions, or a ticket key. Only the authenticated conversation owner may give feedback, access
the linked draft, or confirm submission. The draft description contains a bounded, filtered
summary of recent user messages rather than an unbounded raw transcript. Prompt-injection-shaped
messages are excluded.

Clients must display the proposed solution and server-supplied citations before soliciting
feedback. For unresolved outcomes they must present the returned draft for user review and use the
ordinary draft edit and validation endpoints before enabling explicit confirmation. A missing
confirmation request, stale row version, invalid draft state, or missing idempotency key must be
treated as a non-submission.

## Runtime configuration

The following settings bound resource usage and can be set through the corresponding uppercase
environment variables:

- `AI_AGENT_TURN_TIMEOUT_SECONDS`
- `AI_CANCELLATION_POLL_SECONDS`
- `AI_CONVERSATION_MAX_MESSAGES`
- `AI_CONVERSATION_MAX_CONTEXT_CHARACTERS`
- `AI_EMPLOYEE_MAX_EVIDENCE`
- `AI_EMPLOYEE_MINIMUM_EVIDENCE_SCORE`
- `AI_STREAM_CHUNK_CHARACTERS`

Provider credentials remain secret-manager or environment configuration. They are never written to
conversation, evidence, audit, or stream payloads.
