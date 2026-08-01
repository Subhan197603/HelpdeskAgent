# ADR-0005: Deterministic routing

- Status: Accepted
- Date: 2026-08-01

## Context

Ticket assignment must be explainable, repeatable, and administratively controlled.

## Decision

An LLM may classify a request, but configured deterministic rules select the support group.

## Alternatives

LLM-selected assignment and manual-only triage were rejected.

## Consequences

Routing decisions are auditable and testable; rule governance and fallback handling are required.
