# ADR-0003: pgvector and full-text search

- Status: Accepted
- Date: 2026-08-01

## Context

Knowledge retrieval needs semantic similarity and exact product, module, and release matching.

## Decision

Combine PostgreSQL full-text search with pgvector and governed reranking.

## Alternatives

Vector-only, keyword-only, and a separate search service were rejected for the initial architecture.

## Consequences

Retrieval stays close to authorization data but requires careful indexes, fusion logic, and evaluation.
