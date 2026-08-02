# ADR-0020: Governed fusion and evidence API

## Status

Accepted for Milestone 7, Task 7.2.

## Decision

Fuse only the lexical and vector candidates returned by the authorization-first Task 7.1 queries.
Normalize the source scores for diagnostics and use configurable reciprocal-rank fusion, exact
identifier, applicability, and source-authority components to produce a deterministic final order.
The effective configuration is the tenant-specific or global published `HYBRID_EVIDENCE` version;
invalid or missing configuration fails closed. The API returns its immutable version identifier and
score components, but never returns weights, RRF constants, provider configuration, or secrets.

Query embeddings are generated server-side. Development and tests may use the explicit
non-semantic deterministic adapter. Production requires an approved HTTPS embedding provider.
Reranking is disabled in the bootstrap configuration and can run only when both the published
configuration and deployment settings enable an approved HTTPS adapter. Only already-authorized,
bounded candidates may cross that adapter boundary.

The bootstrap configuration is inserted by migration `0016_retrieval_fusion`. Its published row is
protected by the baseline immutability trigger, so downgrade intentionally retains it; re-upgrade is
idempotent. Later changes must publish a new version instead of altering version 1.

## Consequences

Evidence contains canonical URI, document/version/chunk identifiers, section and page metadata,
release and product applicability, content, and explainable score components. Overdue-review,
retired, unpublished, cross-tenant, and ACL-denied material remains outside both the intermediate
candidate set and final evidence. Task 7.2 adds no LLM prompting or agent behavior.
