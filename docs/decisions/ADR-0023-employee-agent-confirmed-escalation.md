# ADR-0023: Employee-agent confirmed ticket escalation

- Status: Accepted
- Date: 2026-08-03

## Context

The employee helpdesk agent can present evidence-backed proposed solutions, but unresolved issues
must enter the established service-catalogue ticket workflow without giving the model authority to
mutate operational records. Escalation also needs useful conversation context without copying an
unbounded or unsafe transcript into the ticket.

## Decision

Resolution feedback is an append-only, owner-scoped outcome for a conversation. A resolved outcome
closes the conversation without creating a draft. An unresolved outcome must identify an existing
published catalogue item and exact active form schema/version. The employee-agent service calls the
existing ticket service to create one conversation-linked draft; it does not create a ticket.

The draft remains governed by the ordinary user review, edit, validation, optimistic-locking, and
authorization flow. Submission is available only through a separate explicit confirmation endpoint
with an idempotency key and current row version. That endpoint delegates to the ticket service, so
priority, routing, workflow state, audit/outbox records, and the ticket key remain server-derived.
Repeated confirmation returns the already submitted backend ticket.

The draft carries a bounded summary of recent user messages. Prompt-injection-shaped content is
excluded, individual excerpts and the combined summary are capped, and raw assistant/model output
is not copied into the ticket description. Conversation, draft, feedback, and ticket links are
tenant- and user-scoped. The model is never given a ticket mutation tool.

## Consequences

- A ticket cannot exist before the employee reviews and explicitly confirms a valid draft.
- The AI cannot invent ticket keys or choose protected ticket attributes.
- Duplicate feedback, drafts, and submissions are prevented or replayed idempotently.
- Support staff retain bounded conversation provenance without storing an unbounded transcript in
  the ticket.
- Clients must implement a distinct feedback, draft-review, validation, and confirmation sequence.
