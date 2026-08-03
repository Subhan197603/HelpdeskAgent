# ADR-0021: AI provider and authorized-tool runtime

Status: accepted for Milestone 8, Task 8.1

## Decision

The application uses provider-independent request/result contracts. OpenAI and Anthropic adapters
resolve database model aliases through an environment-owned allow-list; database policy never stores
deployments or credentials. A deterministic fake provider is the required test boundary.

Every provider call is gated by both the environment kill switch and the effective approved database
policy. The runtime enforces configured timeouts, bounded retry of retryable failures, an in-process
circuit breaker, explicit-only fallback, request/tool limits, rate limits, and hard budget stops. An
`ai.agent_run` is created with immutable agent, prompt, tool-set, retrieval, model-policy, and feature-
policy version references. Completion appends `ai.usage_ledger`; failures retain only a safe error code.

Tools are registered by stable name with Pydantic input models, a required centralized permission, and
an input-aware authorization hook for resource-level policy. The original `RequestContext` crosses the
tool boundary unchanged. A safe pre-execution audit event is
written before execution without arguments, and the final typed request/result and authorization
outcome are stored in the append-only `ai.tool_call` and general audit streams. Tool implementations
must return already-redacted `ToolResult` values.

No AI endpoint or agent state machine is introduced in this task. Existing ticketing services do not
depend on this runtime and remain available when AI is disabled, unavailable, over budget, or circuit-
broken.

## Consequences

- Production provider endpoints require HTTPS and secrets remain in the platform secret manager.
- Provider/model aliases are deploy-time allow-listed and can be rotated without changing published
  database policy.
- Circuit state is process-local; distributed circuit administration remains future backlog work.
- Concrete employee and analyst tools and their agent orchestration belong to later approved tasks.
