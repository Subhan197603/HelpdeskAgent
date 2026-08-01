# ADR-0004: Tool-mediated LLM access

- Status: Accepted
- Date: 2026-08-01

## Context

Models cannot be trusted with unrestricted data access or state mutation.

## Decision

Models may request allowlisted tools; the backend validates identity, authorization, arguments, and state before execution.

## Alternatives

Direct database, browser, and unrestricted SQL access were rejected.

## Consequences

Every tool needs schemas, policy enforcement, audit records, limits, and tests.
