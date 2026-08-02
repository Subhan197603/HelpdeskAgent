# Hybrid retrieval operations

Milestone 7, Task 7.1 provides an internal authorization-first retrieval service. It does not add a
public evidence endpoint, result fusion, reranking, or LLM integration.

## Runtime limits

`RETRIEVAL_MAX_RESULTS` bounds each lexical and vector candidate list and cannot exceed 50.
`RETRIEVAL_STATEMENT_TIMEOUT_MS` applies a transaction-local PostgreSQL deadline.
`RETRIEVAL_TIMEOUT_SECONDS` is the outer application cancellation deadline. Keep the application
deadline slightly above the database deadline so PostgreSQL normally cancels and cleans up first.

The caller supplies a 1536-dimensional query embedding and its approved model code. Do not log the
query text, embedding values, document content, or rejected candidate identifiers.

## Authorization and filters

Both search strategies enforce the same SQL eligibility boundary before returning candidates:

- authenticated tenant and user;
- active, approved, current, validated, published documents;
- active and approved sources;
- effective dates;
- employee or analyst audience and classification limits;
- explicit user, role, support-group, business-unit, all-employee, or all-analyst document ACLs;
- exact product, module, release-family, release, language, and source filters.

A document without explicit permission rows uses its published audience and classification. Once
any document permission exists, at least one principal must match. Department permissions fail
closed because the current authenticated context has no trusted department attribute.

## Diagnostics

Check `pg_stat_statements`, deadline cancellations, and index plans without copying query or content
values into operational records. Full-text plans should use `kb_document_chunk_fts_ix`; vector
nearest-neighbour plans should use `kb_chunk_embedding_1536_hnsw_ix`. ACL and metadata lookups use
the Task 7.1 indexes added by migration `0015_hybrid_retrieval`.

If release results appear mixed, require both the release family and release code. `26C` belongs to
`FUSION_APPLICATIONS`; `26.R2` belongs to `FUSION_DATA_INTELLIGENCE`. Do not infer one family from a
similarly formatted code in another family.
