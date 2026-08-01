# ADR-0001: Modular monolith

- Status: Accepted
- Date: 2026-08-01

## Context

The helpdesk spans many business capabilities, but premature distribution would add operational and consistency costs.

## Decision

Deploy one backend with explicit module API, application, domain, repository, schema, and test boundaries. Modules call other modules through public application services.

## Alternatives

A microservice architecture and an unstructured monolith were rejected.

## Consequences

Transactions and local development remain simpler. Boundary discipline is required so modules can be extracted later.
