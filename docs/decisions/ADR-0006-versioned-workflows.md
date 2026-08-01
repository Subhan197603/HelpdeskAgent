# ADR-0006: Versioned workflows

- Status: Accepted
- Date: 2026-08-01

## Context

Changing a workflow must not reinterpret the lifecycle of existing tickets.

## Decision

Publish immutable workflow versions and pin each ticket to the applicable version.

## Alternatives

Mutable shared workflow definitions were rejected.

## Consequences

Behavior remains reproducible, with added lifecycle and migration management.
