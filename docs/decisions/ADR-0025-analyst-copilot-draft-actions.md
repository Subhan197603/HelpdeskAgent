# ADR-0025: Analyst copilot draft actions stay behind normal ticket services

- Status: Accepted
- Date: 2026-08-03

## Context

Task 9.2 adds evidence-backed public-response, internal-note, and resolution-summary drafts to the
analyst copilot. A draft is model inference over untrusted ticket and evidence content, so it must
never mutate a ticket on its own, must expose which claims are evidence-backed, and must keep the
analyst as the explicit actor for any posted comment or workflow transition.

## Decision

Draft generation reuses the Task 9.1 evidence assembly (analyst-ticket visibility, similar
resolved tickets, approved runbooks, release-filtered Oracle documentation) and asks the provider
for JSON claims only, with an empty tool set. The server parses that output defensively: claims may
cite only server-supplied citation identifiers, fabricated identifiers are dropped, claims without
surviving citations are marked unsupported, and malformed output degrades to a single unsupported
claim. Draft bodies visibly prefix unsupported claims with `[Unverified]`.

Drafting a kind requires the same permission as acting on it (`TICKET_COMMENT_PUBLIC`,
`TICKET_COMMENT_INTERNAL`, or `TICKET_TRANSITION`) in addition to `AI_ANALYST_USE`. Drafts are
stored as `ASSISTANT` messages inside a ticket-linked `ANALYST_COPILOT` conversation together with
their claims and server-bound citation labels; the governed AI gateway records the full version
capture on `ai.agent_run`.

Posting and resolving are separate explicit analyst actions. Posting sends the analyst-edited body
through the existing analyst comment service; resolving sends the analyst-edited resolution
summary through the existing workflow transition service with its normal authorization, optimistic
concurrency, guard, and event behavior. Both actions append a server-built `Sources:` block from
the draft's citation labels, derive their idempotency key from the draft identifier so retries and
concurrent duplicates collapse into one business effect, and mark the draft actioned with an
append-only `SYSTEM` message under a conversation row lock. An actioned draft cannot be posted or
resolved again.

## Consequences

- The copilot still has no code path that updates `itsm` tables directly; all mutations flow
  through `QueueService.add_comment` and `WorkflowService.execute` with the analyst's context.
- Whether the analyst edited the draft before acting is recorded for later Task 9.3 feedback.
- Citations survive into posted comments and resolution summaries as required by policy.
- A draft is single-use: repeat or concurrent post/resolve attempts return a conflict instead of
  duplicating comments or transitions.
- Provider failures, malformed output, and empty evidence produce safe unsupported drafts or
  normal gateway errors; nothing is posted without an explicit analyst action.
