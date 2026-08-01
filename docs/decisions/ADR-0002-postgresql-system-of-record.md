# ADR-0002: PostgreSQL as system of record

- Status: Accepted
- Date: 2026-08-01

## Context

Ticket state, authorization, approvals, and evidence require durable transactional truth.

## Decision

PostgreSQL controls authoritative application state. Browsers, models, and generic SQL tools never mutate ticket tables directly.

## Alternatives

LLM-managed state and independent stores per module were rejected.

## Consequences

State changes must pass through application services and transactions; database availability is critical.
