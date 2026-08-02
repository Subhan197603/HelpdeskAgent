"""PostgreSQL full-text and pgvector candidate retrieval with hard SQL ACLs."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.retrieval.models import (
    CandidateKind,
    RetrievalCandidate,
    RetrievalConfiguration,
    RetrievalFilters,
)


class RetrievalQueryTimeout(RuntimeError):
    """PostgreSQL cancelled retrieval at its transaction-local deadline."""


@dataclass(frozen=True, slots=True)
class RetrievalPrincipal:
    tenant_id: UUID
    user_id: UUID
    role_codes: tuple[str, ...]
    support_group_codes: tuple[str, ...]
    business_unit_code: str | None
    audience_codes: tuple[str, ...]
    security_levels: tuple[str, ...]
    persona: str


_ELIGIBLE_CTE = """
WITH RECURSIVE eligible_documents AS MATERIALIZED (
  SELECT d.document_id,d.tenant_id,d.source_id,d.product_node_id,d.release_id,
    d.document_title,d.language_code,s.source_type,s.canonical_location,
    d.canonical_url,r.release_family,r.release_code,
    pn.product_code,pn.product_name,dv.document_version_id,
    dv.published_processing_version_id
  FROM kb.document d
  JOIN kb.document_version dv ON dv.document_id=d.document_id
    AND dv.current_version_flag AND dv.validation_status IN ('PASSED','WARNING')
    AND dv.published_processing_version_id IS NOT NULL
  JOIN kb.source s ON s.source_id=d.source_id AND s.active_flag
    AND s.source_status='ACTIVE' AND s.approval_status='APPROVED'
  LEFT JOIN kb.release r ON r.release_id=d.release_id
  LEFT JOIN kb.product_node pn ON pn.product_node_id=d.product_node_id
  WHERE (d.tenant_id IS NULL OR d.tenant_id=:tenant_id)
    AND d.active_flag AND d.approval_status='APPROVED'
    AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
    AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
    AND (d.next_review_date IS NULL OR d.next_review_date>=CURRENT_DATE)
    AND d.audience_code=ANY(CAST(:audiences AS text[]))
    AND d.security_classification=ANY(CAST(:security_levels AS text[]))
    AND (CAST(:source_ids AS uuid[]) IS NULL
      OR d.source_id=ANY(CAST(:source_ids AS uuid[])))
    AND (CAST(:release_families AS text[]) IS NULL OR r.release_family=ANY(
      CAST(:release_families AS text[])))
    AND (CAST(:release_codes AS text[]) IS NULL
      OR r.release_code=ANY(CAST(:release_codes AS text[])))
    AND (CAST(:language_codes AS text[]) IS NULL
      OR d.language_code=ANY(CAST(:language_codes AS text[])))
    AND (
      NOT EXISTS (
        SELECT 1 FROM kb.document_permission permission
        WHERE permission.document_id=d.document_id
      )
      OR EXISTS (
        SELECT 1 FROM kb.document_permission permission
        WHERE permission.document_id=d.document_id
          AND permission.permission_code IN ('READ','AUTHOR','APPROVE','ADMINISTER')
          AND (
            (permission.principal_type='USER'
              AND permission.principal_code=CAST(:user_id AS text))
            OR (permission.principal_type='ROLE'
              AND permission.principal_code=ANY(CAST(:roles AS text[])))
            OR (permission.principal_type='SUPPORT_GROUP'
              AND (
                permission.principal_code=ANY(CAST(:support_groups AS text[]))
                OR EXISTS (
                  SELECT 1 FROM identity.support_group support_group
                  WHERE support_group.tenant_id=:tenant_id
                    AND support_group.support_group_id=ANY(
                      CAST(:support_groups AS uuid[]))
                    AND support_group.group_code=permission.principal_code)))
            OR (permission.principal_type='BUSINESS_UNIT'
              AND CAST(:business_unit AS text) IS NOT NULL
              AND (
                permission.principal_code=CAST(:business_unit AS text)
                OR EXISTS (
                  SELECT 1 FROM identity.business_unit business_unit
                  WHERE business_unit.tenant_id=:tenant_id
                    AND business_unit.business_unit_id=CAST(:business_unit AS uuid)
                    AND business_unit.business_unit_code=permission.principal_code)))
            OR (permission.principal_type='ALL_EMPLOYEES')
            OR (permission.principal_type='ALL_ANALYSTS' AND :persona='ANALYST')
          )
      )
    )
), product_lineage(
  document_id,node_id,parent_node_id,product_code,product_level,path
) AS (
  SELECT eligible.document_id,node.product_node_id,node.parent_product_node_id,
    node.product_code,node.product_level,ARRAY[node.product_node_id]
  FROM eligible_documents eligible
  JOIN kb.product_node node ON node.product_node_id=eligible.product_node_id
  UNION ALL
  SELECT lineage.document_id,parent.product_node_id,parent.parent_product_node_id,
    parent.product_code,parent.product_level,lineage.path || parent.product_node_id
  FROM product_lineage lineage
  JOIN kb.product_node parent ON parent.product_node_id=lineage.parent_node_id
  WHERE NOT parent.product_node_id=ANY(lineage.path)
), eligible_chunks AS NOT MATERIALIZED (
  SELECT chunk.chunk_id,chunk.document_version_id,eligible.document_id,
    eligible.source_id,eligible.document_title,chunk.heading_path,chunk.section_title,
    chunk.section_anchor,chunk.page_number,chunk.content_text,
    chunk.search_vector,eligible.language_code,eligible.release_family,
    eligible.release_code,
    (SELECT lineage.product_code FROM product_lineage lineage
      WHERE lineage.document_id=eligible.document_id AND lineage.product_level='PRODUCT'
      ORDER BY cardinality(lineage.path) DESC LIMIT 1) AS product_code,
    (SELECT node.product_name FROM product_lineage lineage JOIN kb.product_node node
      ON node.product_node_id=lineage.node_id
      WHERE lineage.document_id=eligible.document_id AND lineage.product_level='PRODUCT'
      ORDER BY cardinality(lineage.path) DESC LIMIT 1) AS product_name,
    (SELECT lineage.product_code FROM product_lineage lineage
      WHERE lineage.document_id=eligible.document_id AND lineage.product_level='MODULE'
      ORDER BY cardinality(lineage.path) DESC LIMIT 1) AS module_code,
    (SELECT node.product_name FROM product_lineage lineage JOIN kb.product_node node
      ON node.product_node_id=lineage.node_id
      WHERE lineage.document_id=eligible.document_id AND lineage.product_level='MODULE'
      ORDER BY cardinality(lineage.path) DESC LIMIT 1) AS module_name,
    eligible.source_type,COALESCE(eligible.canonical_url,eligible.canonical_location) canonical_uri
  FROM eligible_documents eligible
  JOIN kb.document_chunk chunk
    ON chunk.document_version_id=eligible.document_version_id
    AND chunk.processing_version_id=eligible.published_processing_version_id
    AND chunk.tenant_id=:tenant_id
  WHERE (CAST(:product_codes AS text[]) IS NULL OR EXISTS (
      SELECT 1 FROM product_lineage lineage
      WHERE lineage.document_id=eligible.document_id
        AND lineage.product_level='PRODUCT'
        AND lineage.product_code=ANY(CAST(:product_codes AS text[]))))
    AND (CAST(:module_codes AS text[]) IS NULL OR EXISTS (
      SELECT 1 FROM product_lineage lineage
      WHERE lineage.document_id=eligible.document_id
        AND lineage.product_level='MODULE'
        AND lineage.product_code=ANY(CAST(:module_codes AS text[]))))
)
"""

_COLUMNS = """
  chunk_id,document_id,document_version_id,source_id,document_title,heading_path,
  content_text,language_code,release_family,release_code,product_code,product_name,
  module_code,module_name,source_type,canonical_uri,section_title,section_anchor,page_number
"""

_CONFIGURATION = text("""
SELECT version.retrieval_configuration_version_id,version.configuration_json
FROM ai.retrieval_configuration configuration
JOIN ai.retrieval_configuration_version version
  ON version.retrieval_configuration_id=configuration.retrieval_configuration_id
WHERE configuration.active_flag
  AND (configuration.tenant_id=:tenant_id OR configuration.tenant_id IS NULL)
  AND configuration.retrieval_code='HYBRID_EVIDENCE'
  AND version.version_status='PUBLISHED'
  AND (version.effective_from IS NULL OR version.effective_from<=now())
  AND (version.effective_to IS NULL OR version.effective_to>now())
ORDER BY (configuration.tenant_id IS NOT NULL) DESC,version.version_number DESC
LIMIT 1
""")

_LEXICAL = text(
    _ELIGIBLE_CTE
    + """
, lexical_query AS MATERIALIZED (
  SELECT websearch_to_tsquery('english',:query) AS value
), ranked AS (
  SELECT eligible.*,ts_rank_cd(eligible.search_vector,query.value)::real AS score
  FROM eligible_chunks eligible CROSS JOIN lexical_query query
  WHERE eligible.search_vector@@query.value
)
SELECT """
    + _COLUMNS
    + """,score
FROM ranked
ORDER BY score DESC,chunk_id
LIMIT :result_limit
"""
)

_VECTOR = text(
    _ELIGIBLE_CTE
    + """
, ranked AS (
  SELECT eligible.*,
    (1-(embedding.embedding<=>CAST(:query_embedding AS vector(1536))))::real AS score
  FROM eligible_chunks eligible
  JOIN kb.chunk_embedding_1536 embedding ON embedding.chunk_id=eligible.chunk_id
    AND embedding.processing_version_id IS NOT DISTINCT FROM (
      SELECT published_processing_version_id FROM eligible_documents document
      WHERE document.document_id=eligible.document_id)
    AND embedding.embedding_model_code=:embedding_model_code
  JOIN kb.embedding_model model
    ON model.embedding_model_code=embedding.embedding_model_code AND model.active_flag
)
SELECT """
    + _COLUMNS
    + """,score
FROM ranked
ORDER BY score DESC,chunk_id
LIMIT :result_limit
"""
)


class RetrievalRepository:
    def __init__(self, session: AsyncSession, statement_timeout_ms: int) -> None:
        self._session = session
        self._statement_timeout_ms = statement_timeout_ms

    async def lexical(
        self,
        principal: RetrievalPrincipal,
        query: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        return await self._execute(
            _LEXICAL,
            CandidateKind.LEXICAL,
            principal,
            filters,
            limit,
            {"query": query},
        )

    async def configuration(self, tenant_id: UUID) -> RetrievalConfiguration | None:
        await self._session.execute(
            text("SELECT set_config('statement_timeout',:timeout,true)"),
            {"timeout": f"{self._statement_timeout_ms}ms"},
        )
        try:
            row = (
                await self._session.execute(_CONFIGURATION, {"tenant_id": tenant_id})
            ).one_or_none()
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise RetrievalQueryTimeout("Retrieval statement deadline exceeded") from error
            raise
        if row is None:
            return None
        values = row.configuration_json
        if not isinstance(values, dict):
            return None
        try:
            authority = values.get("source_authority_weights", {})
            if not isinstance(authority, dict) or not isinstance(
                values.get("reranking_enabled"), bool
            ):
                return None
            configuration = RetrievalConfiguration(
                version_id=row.retrieval_configuration_version_id,
                rrf_k=int(values["rrf_k"]),
                lexical_weight=float(values["lexical_weight"]),
                vector_weight=float(values["vector_weight"]),
                exact_identifier_boost=float(values["exact_identifier_boost"]),
                metadata_boost=float(values["metadata_boost"]),
                rerank_weight=float(values["rerank_weight"]),
                reranking_enabled=bool(values["reranking_enabled"]),
                source_authority_weights={
                    str(key): float(value) for key, value in authority.items()
                },
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not _valid_configuration(configuration):
            return None
        return configuration

    async def vector(
        self,
        principal: RetrievalPrincipal,
        query_embedding: tuple[float, ...],
        embedding_model_code: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> tuple[RetrievalCandidate, ...]:
        vector = "[" + ",".join(format(value, ".17g") for value in query_embedding) + "]"
        return await self._execute(
            _VECTOR,
            CandidateKind.VECTOR,
            principal,
            filters,
            limit,
            {"query_embedding": vector, "embedding_model_code": embedding_model_code},
        )

    async def _execute(
        self,
        statement: Any,
        kind: CandidateKind,
        principal: RetrievalPrincipal,
        filters: RetrievalFilters,
        limit: int,
        additional: dict[str, object],
    ) -> tuple[RetrievalCandidate, ...]:
        await self._session.execute(
            text("SELECT set_config('statement_timeout',:timeout,true)"),
            {"timeout": f"{self._statement_timeout_ms}ms"},
        )
        parameters: dict[str, object] = {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "roles": list(principal.role_codes),
            "support_groups": list(principal.support_group_codes),
            "business_unit": principal.business_unit_code,
            "audiences": list(principal.audience_codes),
            "security_levels": list(principal.security_levels),
            "persona": principal.persona,
            "source_ids": _optional(filters.source_ids),
            "release_families": _optional(filters.release_families),
            "release_codes": _optional(filters.release_codes),
            "language_codes": _optional(filters.language_codes),
            "product_codes": _optional(filters.product_codes),
            "module_codes": _optional(filters.module_codes),
            "result_limit": limit,
            **additional,
        }
        try:
            rows = (await self._session.execute(statement, parameters)).all()
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "57014":
                raise RetrievalQueryTimeout("Retrieval statement deadline exceeded") from error
            raise
        return tuple(
            RetrievalCandidate(
                rank=rank,
                kind=kind,
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                source_id=row.source_id,
                document_title=row.document_title,
                heading_path=row.heading_path,
                content_text=row.content_text,
                language_code=row.language_code,
                release_family=row.release_family,
                release_code=row.release_code,
                product_code=row.product_code,
                product_name=row.product_name,
                module_code=row.module_code,
                module_name=row.module_name,
                source_type=row.source_type,
                canonical_uri=row.canonical_uri,
                section_title=row.section_title,
                section_anchor=row.section_anchor,
                page_number=row.page_number,
                score=float(row.score),
            )
            for rank, row in enumerate(rows, start=1)
        )


def _optional(values: tuple[object, ...]) -> list[object] | None:
    return list(values) if values else None


def _valid_configuration(configuration: RetrievalConfiguration) -> bool:
    bounded = (
        configuration.lexical_weight,
        configuration.vector_weight,
        configuration.exact_identifier_boost,
        configuration.metadata_boost,
        *configuration.source_authority_weights.values(),
    )
    return (
        1 <= configuration.rrf_k <= 1000
        and all(0 <= value <= 10 for value in bounded)
        and 0 <= configuration.rerank_weight <= 1
        and configuration.lexical_weight + configuration.vector_weight > 0
        and len(configuration.source_authority_weights) <= 20
        and all(len(key) <= 80 for key in configuration.source_authority_weights)
    )
