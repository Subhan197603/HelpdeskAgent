"""Set-based, tenant-scoped corpus validation persistence."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.knowledge.corpus_validation_models import (
    CorpusValidationFinding,
    CorpusValidationRun,
)

# The scanned corpus: the current (or newest) version of every active document
# visible to the tenant, its latest processing version, and that version's
# chunks. Every detector below operates on this scope only.
_SCOPE_SQL = """
scanned_version AS (
  SELECT doc.document_id,doc.tenant_id AS document_tenant_id,doc.document_title,
    doc.created_at AS document_created_at,dv.document_version_id,dv.sha256_checksum
  FROM kb.document AS doc
  JOIN LATERAL (
    SELECT version.document_version_id,version.sha256_checksum
    FROM kb.document_version AS version
    WHERE version.document_id=doc.document_id
    ORDER BY version.current_version_flag DESC,version.version_number DESC
    LIMIT 1
  ) AS dv ON true
  WHERE doc.active_flag AND (doc.tenant_id=:tenant_id OR doc.tenant_id IS NULL)
),
scanned_processing AS (
  SELECT scanned_version.*,latest.processing_version_id,latest.processing_status,
    latest.validation_status,latest.validation_json
  FROM scanned_version
  LEFT JOIN LATERAL (
    SELECT processing.processing_version_id,processing.processing_status,
      processing.validation_status,processing.validation_json
    FROM kb.document_processing_version AS processing
    WHERE processing.document_version_id=scanned_version.document_version_id
    ORDER BY processing.processing_number DESC LIMIT 1
  ) AS latest ON true
),
scanned_chunk AS (
  SELECT chunk.chunk_id,chunk.chunk_sequence,chunk.content_text,chunk.token_count,
    chunk.content_hash,chunk.tenant_id AS chunk_tenant_id,
    scanned_processing.document_id,scanned_processing.document_tenant_id,
    scanned_processing.document_created_at,scanned_processing.document_version_id
  FROM kb.document_chunk AS chunk
  JOIN scanned_processing
    ON scanned_processing.processing_version_id=chunk.processing_version_id
)
"""

_DUPLICATE_CTE = """
,duplicate_member AS (
  SELECT scanned_version.*,
    count(*) OVER (PARTITION BY sha256_checksum) AS member_count,
    (min(document_id::text) OVER (PARTITION BY sha256_checksum))::uuid AS group_first
  FROM scanned_version WHERE sha256_checksum IS NOT NULL
)
"""

# One near-duplicate finding per pair, attached to the non-canonical member.
# The canonical member (earliest document, then lowest identifiers) is never
# flagged, so the last visible copy always survives. Suppression is limited to
# tenant-owned chunks: a tenant never flags shared global content.
_NEAR_DUPLICATE_CTE = """
,near_pair AS (
  SELECT first_chunk.chunk_id AS first_chunk_id,
    first_chunk.document_id AS first_document_id,
    first_chunk.document_tenant_id AS first_document_tenant_id,
    first_chunk.chunk_tenant_id AS first_chunk_tenant_id,
    first_chunk.document_created_at AS first_created_at,
    first_chunk.document_version_id AS first_version_id,
    second_chunk.chunk_id AS second_chunk_id,
    second_chunk.document_id AS second_document_id,
    second_chunk.document_tenant_id AS second_document_tenant_id,
    second_chunk.chunk_tenant_id AS second_chunk_tenant_id,
    second_chunk.document_created_at AS second_created_at,
    second_chunk.document_version_id AS second_version_id,
    round((1-(first_embedding.embedding<=>second_embedding.embedding))::numeric,4)
      AS similarity
  FROM scanned_chunk AS first_chunk
  JOIN kb.chunk_embedding_1536 AS first_embedding
    ON first_embedding.chunk_id=first_chunk.chunk_id
  JOIN scanned_chunk AS second_chunk
    ON second_chunk.document_id<>first_chunk.document_id
    AND first_chunk.chunk_id<second_chunk.chunk_id
  JOIN kb.chunk_embedding_1536 AS second_embedding
    ON second_embedding.chunk_id=second_chunk.chunk_id
  WHERE (1-(first_embedding.embedding<=>second_embedding.embedding))>=:threshold
),
near_finding AS (
  SELECT CASE WHEN canonical_first THEN second_document_id
    ELSE first_document_id END AS flagged_document_id,
    CASE WHEN canonical_first THEN second_version_id
      ELSE first_version_id END AS flagged_version_id,
    CASE WHEN canonical_first THEN second_chunk_id
      ELSE first_chunk_id END AS flagged_chunk_id,
    CASE WHEN canonical_first THEN second_document_tenant_id
      ELSE first_document_tenant_id END AS flagged_document_tenant_id,
    CASE WHEN canonical_first THEN second_chunk_tenant_id
      ELSE first_chunk_tenant_id END AS flagged_chunk_tenant_id,
    CASE WHEN canonical_first THEN first_document_id
      ELSE second_document_id END AS canonical_document_id,
    CASE WHEN canonical_first THEN first_chunk_id
      ELSE second_chunk_id END AS canonical_chunk_id,
    similarity,
    md5(least(first_chunk_id,second_chunk_id)::text||':'||
      greatest(first_chunk_id,second_chunk_id)::text) AS pair_key
  FROM (
    SELECT near_pair.*,
      (first_created_at,first_document_id,first_chunk_id)
        <=(second_created_at,second_document_id,second_chunk_id) AS canonical_first
    FROM near_pair
  ) AS ordered_pair
)
"""

_INSERT_PREFIX = """
INSERT INTO kb.corpus_validation_finding(
  run_id,tenant_id,finding_type,document_id,document_version_id,chunk_id,
  counterpart_document_id,counterpart_chunk_id,duplicate_group_key,
  similarity_score,suppression_flagged,evidence_json)
"""

_RUN_SELECT = """
SELECT run_id,tenant_id,run_status,requested_by,similarity_threshold,document_count,
  chunk_count,structural_defect_count,empty_chunk_count,duplicate_document_count,
  near_duplicate_chunk_count,truncated_flag,started_at,completed_at,created_at,
  row_version
FROM kb.corpus_validation_run
"""

_FINDING_LIMIT = 200


class CorpusValidationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self,
        run_id: UUID,
        tenant_id: UUID,
        actor_user_id: UUID,
        similarity_threshold: float,
        correlation_id: str,
        request_id: str,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO kb.corpus_validation_run(
                  run_id,tenant_id,requested_by,similarity_threshold,
                  correlation_id,request_id)
                VALUES (:run_id,:tenant_id,:actor_user_id,:threshold,
                  CAST(:correlation_id AS uuid),:request_id)
            """),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "threshold": similarity_threshold,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

    async def corpus_counts(self, tenant_id: UUID) -> tuple[int, int]:
        row = (
            await self._session.execute(
                text(
                    "WITH "
                    + _SCOPE_SQL
                    + """
                    SELECT (SELECT count(*) FROM scanned_version) AS documents,
                      (SELECT count(*) FROM scanned_chunk) AS chunks
                    """
                ),
                {"tenant_id": tenant_id},
            )
        ).one()
        return int(row.documents), int(row.chunks)

    async def insert_structural_findings(self, run_id: UUID, tenant_id: UUID) -> tuple[int, bool]:
        return await self._capped_insert(
            "",
            "SELECT count(*) FROM scanned_processing "
            "WHERE processing_status='FAILED' OR validation_status='FAILED'",
            """
            SELECT :run_id,:tenant_id,'STRUCTURAL_DEFECT',document_id,
              document_version_id,NULL,NULL,NULL,NULL,NULL,false,
              jsonb_build_object(
                'processing_status',processing_status,
                'validation_status',validation_status,
                'failures',coalesce(validation_json->'failures','[]'::jsonb))
            FROM scanned_processing
            WHERE processing_status='FAILED' OR validation_status='FAILED'
            ORDER BY document_id
            """,
            {"run_id": run_id, "tenant_id": tenant_id},
        )

    async def insert_empty_chunk_findings(self, run_id: UUID, tenant_id: UUID) -> tuple[int, bool]:
        return await self._capped_insert(
            "",
            "SELECT count(*) FROM scanned_chunk WHERE btrim(content_text)='' OR token_count=0",
            """
            SELECT :run_id,:tenant_id,'EMPTY_CHUNK',document_id,document_version_id,
              chunk_id,NULL,NULL,NULL,NULL,false,
              jsonb_build_object('chunk_sequence',chunk_sequence,
                'token_count',coalesce(token_count,0))
            FROM scanned_chunk
            WHERE btrim(content_text)='' OR token_count=0
            ORDER BY document_id,chunk_sequence
            """,
            {"run_id": run_id, "tenant_id": tenant_id},
        )

    async def insert_duplicate_document_findings(
        self, run_id: UUID, tenant_id: UUID
    ) -> tuple[int, bool]:
        return await self._capped_insert(
            _DUPLICATE_CTE,
            "SELECT count(*) FROM duplicate_member WHERE member_count>1",
            """
            SELECT :run_id,:tenant_id,'DUPLICATE_DOCUMENT',document_id,
              document_version_id,NULL,
              CASE WHEN document_id=group_first THEN NULL ELSE group_first END,
              NULL,sha256_checksum,NULL,false,
              jsonb_build_object('member_count',member_count)
            FROM duplicate_member WHERE member_count>1
            ORDER BY sha256_checksum,document_id
            """,
            {"run_id": run_id, "tenant_id": tenant_id},
        )

    async def insert_near_duplicate_findings(
        self, run_id: UUID, tenant_id: UUID, threshold: float
    ) -> tuple[int, bool]:
        return await self._capped_insert(
            _NEAR_DUPLICATE_CTE,
            "SELECT count(*) FROM near_finding",
            """
            SELECT :run_id,:tenant_id,'NEAR_DUPLICATE_CHUNK',flagged_document_id,
              flagged_version_id,flagged_chunk_id,canonical_document_id,
              canonical_chunk_id,pair_key,similarity,
              (flagged_document_tenant_id IS NOT NULL
                AND flagged_chunk_tenant_id=:tenant_id),
              jsonb_build_object('similarity',similarity)
            FROM near_finding
            ORDER BY similarity DESC,flagged_chunk_id,canonical_chunk_id
            """,
            {"run_id": run_id, "tenant_id": tenant_id, "threshold": threshold},
        )

    async def apply_suppression_flags(self, run_id: UUID, tenant_id: UUID) -> int:
        await self._session.execute(
            text(
                "WITH "
                + _SCOPE_SQL
                + """
                UPDATE kb.document_chunk SET near_duplicate_suppressed_flag=false
                WHERE near_duplicate_suppressed_flag
                  AND tenant_id=:tenant_id
                  AND chunk_id IN (SELECT chunk_id FROM scanned_chunk)
                """
            ),
            {"tenant_id": tenant_id},
        )
        result: Any = await self._session.execute(
            text("""
                UPDATE kb.document_chunk SET near_duplicate_suppressed_flag=true
                WHERE tenant_id=:tenant_id AND chunk_id IN (
                  SELECT finding.chunk_id FROM kb.corpus_validation_finding AS finding
                  WHERE finding.run_id=:run_id AND finding.suppression_flagged
                    AND finding.chunk_id IS NOT NULL
                )
            """),
            {"run_id": run_id, "tenant_id": tenant_id},
        )
        return int(result.rowcount or 0)

    async def finalize_run(
        self,
        run_id: UUID,
        tenant_id: UUID,
        *,
        document_count: int,
        chunk_count: int,
        structural_defects: int,
        empty_chunks: int,
        duplicate_documents: int,
        near_duplicate_chunks: int,
        truncated: bool,
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE kb.corpus_validation_run SET run_status='COMPLETED',
                  document_count=:document_count,chunk_count=:chunk_count,
                  structural_defect_count=:structural_defects,
                  empty_chunk_count=:empty_chunks,
                  duplicate_document_count=:duplicate_documents,
                  near_duplicate_chunk_count=:near_duplicate_chunks,
                  truncated_flag=:truncated,completed_at=now(),
                  row_version=row_version+1
                WHERE run_id=:run_id AND tenant_id=:tenant_id
            """),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "document_count": document_count,
                "chunk_count": chunk_count,
                "structural_defects": structural_defects,
                "empty_chunks": empty_chunks,
                "duplicate_documents": duplicate_documents,
                "near_duplicate_chunks": near_duplicate_chunks,
                "truncated": truncated,
            },
        )

    async def latest_run(self, tenant_id: UUID) -> CorpusValidationRun | None:
        row = (
            await self._session.execute(
                text(
                    _RUN_SELECT
                    + "WHERE tenant_id=:tenant_id "
                    + "ORDER BY created_at DESC,run_id DESC LIMIT 1"
                ),
                {"tenant_id": tenant_id},
            )
        ).one_or_none()
        return CorpusValidationRun(*tuple(row)) if row is not None else None

    async def run(self, tenant_id: UUID, run_id: UUID) -> CorpusValidationRun | None:
        row = (
            await self._session.execute(
                text(_RUN_SELECT + "WHERE tenant_id=:tenant_id AND run_id=:run_id"),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
        ).one_or_none()
        return CorpusValidationRun(*tuple(row)) if row is not None else None

    async def findings(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        finding_type: str | None,
        limit: int,
        offset: int,
    ) -> list[CorpusValidationFinding]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT finding.finding_id,finding.finding_type,finding.document_id,
                      document.document_title,finding.document_version_id,
                      finding.chunk_id,finding.counterpart_document_id,
                      counterpart.document_title,finding.counterpart_chunk_id,
                      finding.duplicate_group_key,finding.similarity_score,
                      finding.suppression_flagged,finding.evidence_json
                    FROM kb.corpus_validation_finding AS finding
                    LEFT JOIN kb.document AS document
                      ON document.document_id=finding.document_id
                    LEFT JOIN kb.document AS counterpart
                      ON counterpart.document_id=finding.counterpart_document_id
                    WHERE finding.tenant_id=:tenant_id AND finding.run_id=:run_id
                      AND (CAST(:finding_type AS varchar) IS NULL
                        OR finding.finding_type=:finding_type)
                    ORDER BY finding.finding_type,finding.finding_id
                    LIMIT :limit OFFSET :offset
                """),
                {
                    "tenant_id": tenant_id,
                    "run_id": run_id,
                    "finding_type": finding_type,
                    "limit": limit,
                    "offset": offset,
                },
            )
        ).all()
        return [CorpusValidationFinding(*tuple(row)) for row in rows]

    async def audit(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        run_id: UUID,
        summary: dict[str, Any],
        correlation_id: str,
        request_id: str,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',
                  'KNOWLEDGE_CORPUS_VALIDATION_RUN','CORPUS_VALIDATION_RUN',
                  CAST(:run_id AS varchar),CAST(:summary AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "run_id": run_id,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

    async def _capped_insert(
        self,
        extra_cte: str,
        count_query: str,
        insert_select: str,
        parameters: dict[str, Any],
    ) -> tuple[int, bool]:
        total = int(
            await self._session.scalar(
                text("WITH " + _SCOPE_SQL + extra_cte + " " + count_query), parameters
            )
            or 0
        )
        if total > 0:
            await self._session.execute(
                text(
                    "WITH "
                    + _SCOPE_SQL
                    + extra_cte
                    + _INSERT_PREFIX
                    + insert_select
                    + f" LIMIT {_FINDING_LIMIT}"
                ),
                parameters,
            )
        return total, total > _FINDING_LIMIT
