# ADR-0026: Analyst copilot feedback, oversight metrics, and evaluation data

- Status: Accepted
- Date: 2026-08-03

## Context

Task 9.3 closes the analyst copilot loop: analysts must be able to record whether copilot output
was approved, edited, or rejected and why; administrators need usage and outcome visibility and a
safe dataset for offline evaluation; and the safety boundaries from Tasks 9.1 and 9.2 must hold
under provider failure, prompt-injection-shaped model output, and AI-disabled operation.

## Decision

Analyst feedback is a first-class append-only record. `ai.feedback` gains constrained
`decision_code` (`APPROVED`, `EDITED`, `REJECTED`) and `reason_code` columns (migration
`0019_analyst_feedback`); a rejection must carry a reason, and a partial unique index allows one
`ANALYST_ACCEPTANCE` row per analyst per agent run. Feedback is submitted through
`POST /api/v1/agent/tickets/{ticket_key}/copilot/runs/{agent_run_id}/feedback`, requires
`AI_ANALYST_USE`, and only the analyst who owns the run's conversation on that ticket can submit
it. Comments are length-bounded, contact-data redacted, and replaced entirely when they are
instruction-shaped. Runtime roles keep no UPDATE/DELETE grants on `ai.feedback`.

Oversight is a separate, administrator-only surface guarded by the new `AI_OVERSIGHT`
permission, granted to `AI_ADMIN` and `PLATFORM_ADMIN`.
`GET /api/v1/admin/ai/copilot/metrics` reports tenant-scoped usage and outcome counts (runs,
drafts, posted, resolved, feedback by decision) derived from the immutable conversation, message,
and feedback records. `GET /api/v1/admin/ai/copilot/evaluation-dataset` returns bounded,
PII-redacted records — claims with their server-bound citations and supported flags plus the
analyst decision — with no user identities, ticket keys, or raw ticket content. In-process
`CopilotMetrics` counters (including provider failures) mirror the existing service-metrics
pattern for operational monitoring.

Safety hardening: instruction-shaped model claims are neutralized to an excluded-content marker
and marked unsupported, so injection-shaped provider output cannot reach analysts as advice. All
provider calls stay behind the governed gateway with its policy, budget, timeout, retry, and
circuit-breaker limits; provider failures increment a metric and surface as normal fail-closed
errors. Posting an existing draft and every deterministic ticketing path work with AI disabled.

## Consequences

- Every copilot recommendation now has a recordable analyst outcome for Task 10.2's AI
  evaluation thresholds, and rejected output always carries a machine-readable reason.
- Analysts cannot see or use oversight endpoints; administrators cannot submit analyst feedback
  through the oversight surface.
- Evaluation data can be exported without exposing personal data, ticket identities, or
  analyst-only source content beyond the claims the copilot already produced.
- Feedback is immutable and single-shot per run; corrections require a new run, preserving the
  decision history.
- The copilot still cannot mutate tickets: feedback, metrics, and dataset reads add no new
  mutation path, and the draft/post/resolve boundary from ADR-0025 is unchanged.
