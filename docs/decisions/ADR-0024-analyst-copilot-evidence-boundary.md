# ADR-0024: Analyst copilot evidence and mutation boundary

- Status: Accepted
- Date: 2026-08-03

## Context

Analysts need a concise ticket summary, comparable validated resolutions, internal runbooks, and
release-applicable Oracle documentation. These sources have different authorization and content
classifications. Ticket descriptions, comments, historical resolutions, and retrieved documents
are all untrusted model input. A copilot response must not become an alternate route for assigning,
prioritizing, commenting on, transitioning, or otherwise mutating a ticket.

## Decision

The analyst copilot is a read-only application service guarded by the dedicated
`AI_ANALYST_USE` permission, granted only to analyst roles. It first resolves the target through the
existing analyst-ticket service, preserving tenant and support-group visibility. Similar tickets
must be resolved or closed, have a non-empty resolution, belong to the same project, and remain
visible through the caller's group or all-ticket permission. Returned historical fields exclude
user identities and redact common personal contact data.

Knowledge retrieval uses the existing `ANALYST` persona. Its SQL authorization continues to
enforce tenant, audience, security-classification, document-principal, support-group, business-unit,
and source constraints. Internal runbooks are approved `RUNBOOK` documents. Oracle evidence comes
only from `ORACLE_PUBLIC_DOCUMENTATION`; when the ticket has a configured current environment
release, retrieval is filtered to that exact release family and code.

The provider receives bounded, classified, redacted context and selected evidence only. Content
that resembles prompt instructions is excluded. The provider receives an empty tool set. Its
output is labelled as inference and is presented only when the server can bind it to authorized
historical-ticket or knowledge citations. Citation identifiers, URIs, release metadata, and scores
are built from server-side retrieval records, not model output.

Each request creates a ticket-linked `ANALYST_COPILOT` conversation. The governed AI gateway
captures the agent configuration, prompt, tool set, model policy, provider/model, feature policy,
and retrieval-policy versions in `ai.agent_run`. The application persists the actual knowledge
retrieval version and selected knowledge and historical-ticket evidence. Conversation and run
ownership are checked again when the result is finalized.

## Consequences

- Employees cannot invoke or retrieve analyst copilot output.
- Internal activity remains explicitly classified as public, internal, or system content.
- Similar tickets and knowledge cannot cross tenant, project, group, or source ACL boundaries.
- Recommendations are visibly inferential and always carry server-bound citations.
- The copilot has no method or tool capable of mutating tickets; later draft/post actions remain a
  separately approved task using normal workflow services.
- Deployments must publish an `ANALYST_COPILOT` agent configuration for the `TICKET_ANALYSIS` use
  case before model-backed analysis is available.
