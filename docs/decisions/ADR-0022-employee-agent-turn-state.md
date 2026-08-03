# ADR-0022: Employee-agent turn state and streaming boundary

Status: accepted for Milestone 8, Task 8.2

## Decision

Revision `0017_employee_agent` adds a tenant-scoped `ai.conversation_turn` runtime table. It records
the explicit state, outcome, user and assistant messages, retrieval-configuration version, provider
run, cancellation, and safe failure code for each turn. A partial unique index permits only one active
turn per conversation, providing the database backstop for concurrent stream isolation.

The employee chat API may write the existing AI conversation, message, run, evidence, and usage
tables through `helpdesk_app`. Append-only evidence and ledger tables retain their update/delete
prohibitions. Conversation ownership is enforced in every repository query in addition to tenant RLS.

Server-sent events are used for streaming. Disconnect cancellation is propagated to the provider and
persisted on both run and turn. Retrieved content remains untrusted data, employee retrieval runs
before any resolution, and citations are constructed deterministically from authorized evidence.

## Downgrade

Downgrade revokes the API runtime grants, drops `ai.conversation_turn`, and removes the companion
message-history index. Existing conversation, message, run, usage, and evidence rows are retained.
Dropping the turn table is destructive and is approved only for reviewed rollback of revision
`0017_employee_agent`.
