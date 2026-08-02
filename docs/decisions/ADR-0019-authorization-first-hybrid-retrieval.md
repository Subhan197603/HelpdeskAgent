# ADR-0019: Authorization-first hybrid retrieval

- Status: Accepted
- Date: 2026-08-02

## Context

Published knowledge must support PostgreSQL full-text and pgvector similarity searches without
placing unauthorized chunks into application candidate lists. Retrieval also needs exact product,
module, release-family, release, language, and source filtering while preserving the distinction
between Fusion Applications `26C` and Fusion Data Intelligence `26.R2`.

## Decision

Build an internal retrieval service that returns separate, deterministically ordered lexical and
vector candidate lists. Each SQL statement first materializes eligible documents using tenant,
publication, effective-date, source-governance, persona, classification, and document-principal
rules. Product hierarchy and metadata filters are applied before candidates are returned. Scoring
remains separate so reciprocal-rank fusion, reranking, and the evidence API can be added in Task 7.2.

Use transaction-local PostgreSQL statement deadlines plus an application cancellation deadline.
Bound result counts and query size. Continue using the baseline GIN full-text and HNSW cosine
indexes, with additional ACL and metadata lookup indexes introduced through Alembic.

## Consequences

Authorization is duplicated in the two SQL strategies but remains explicit and testable. The API
does not expose retrieval yet. Future fusion must consume these already-authorized candidate lists
and must not re-query an unfiltered corpus.
