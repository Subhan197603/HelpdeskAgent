# ADR-0010: Provider-independent LLM interface

- Status: Accepted
- Date: 2026-08-01

## Context

The product must support OpenAI and Anthropic without leaking provider details into domain logic.

## Decision

Place provider-specific SDKs, model names, and response mapping behind application-owned interfaces and configuration.

## Alternatives

Direct provider SDK use throughout the codebase and a single hard-coded provider were rejected.

## Consequences

Adapters require contract tests; capabilities must be normalized without hiding meaningful provider differences.
