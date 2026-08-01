# ADR-0007: Transactional outbox

- Status: Accepted
- Date: 2026-08-01

## Context

Database changes and asynchronous side effects must not diverge after partial failure.

## Decision

Write outbox events in the same transaction as authoritative state, then process them idempotently.

## Alternatives

Publishing directly inside requests and distributed transactions were rejected.

## Consequences

Delivery is at least once; consumers need idempotency, retries, backlog monitoring, and dead-letter handling.
