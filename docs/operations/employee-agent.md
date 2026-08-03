# Employee helpdesk agent

Milestone 8, Task 8.2 adds an employee-authorized, retrieval-first conversation API. It does not
create ticket drafts, collect resolution feedback, or submit tickets; those actions remain part of
the separately approved Task 8.3 workflow.

## API

- `POST /api/v1/assistant/conversations` creates an owner-scoped conversation.
- `GET /api/v1/assistant/conversations/{conversation_id}` returns its current state to its owner.
- `POST /api/v1/assistant/conversations/{conversation_id}/messages` returns server-sent events.
- `POST /api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/cancel` cancels an
  active, owner-scoped turn.

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
failed-prior-solution messages immediately recommend human escalation. No path in this task calls
the ticket service or invents a ticket key. AI-disabled, provider-failure, circuit-breaker, timeout,
and cancellation paths leave deterministic ticketing available.

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
