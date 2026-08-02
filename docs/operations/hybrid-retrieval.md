# Hybrid retrieval operations

Milestone 7, Tasks 7.1 and 7.2 provide authorization-first retrieval and the authorized evidence
endpoint. They do not add LLM prompting or agent behavior.

## Runtime limits

`RETRIEVAL_MAX_RESULTS` bounds each lexical and vector candidate list and cannot exceed 50.
`RETRIEVAL_STATEMENT_TIMEOUT_MS` applies a transaction-local PostgreSQL deadline.
`RETRIEVAL_TIMEOUT_SECONDS` is the outer application cancellation deadline. Keep the application
deadline slightly above the database deadline so PostgreSQL normally cancels and cleans up first.

The evidence API generates its 1536-dimensional query embedding server-side. Do not log query text,
embedding values, document content, or rejected candidate identifiers.

## Evidence endpoint

`POST /api/v1/knowledge/evidence/search` accepts a bounded query, employee or analyst persona,
metadata filters, and result limit. The response contains selected content, canonical source
metadata, and normalized lexical/vector, fusion, exact-identifier, metadata, source-authority, and
optional rerank components. It includes the effective configuration version ID but not raw weights.

The effective `HYBRID_EVIDENCE` configuration must be active, published, and in its effective
period. A tenant version takes precedence over the global version. Missing or malformed
configuration fails closed. Published versions are immutable; publish a new version for tuning.

Production requires `RETRIEVAL_EMBEDDING_PROVIDER=http`, an approved HTTPS endpoint, and a secret
API key. Reranking additionally requires both the published version and deployment settings to
enable it, with a separately approved HTTPS endpoint and key. Only authorized candidates are sent.

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

Fusion never expands the authorized candidate set. Do not weaken hard SQL filters to compensate
for poor ranking. A document past `next_review_date`, retired, inactive, unpublished, or outside its
effective period is intentionally excluded.

## Regression gate

`tests/ai_evaluation/retrieval_regression_v1.json` pins the approved queries, expected documents,
forbidden documents, and quality/latency thresholds. The PostgreSQL runner verifies authorization
at the candidate and evidence boundaries, canonical evidence joins, release-family isolation,
identifier boosts, stale and retired exclusion, deterministic ordering, empty results, and absence
of restricted canaries from captured logs. Retrieval has no cache; do not add one without a design
review proving tenant/ACL-safe keys and invalidation.

Run the dedicated gate with:

```powershell
uv run pytest tests/integration/test_document_acquisition.py `
  -k retrieval_regression_corpus_quality_acl_evidence_and_latency -m integration
```
