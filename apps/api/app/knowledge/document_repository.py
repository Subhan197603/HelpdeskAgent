"""Transactional document review and immutable publication persistence."""

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.knowledge.document_models import (
    DocumentRecord,
    ProcessingRecord,
    VersionRecord,
)

_DOCUMENT = """
SELECT document_id,tenant_id,source_id,document_title,document_type,audience_code,
  security_classification,approval_status,approved_by,approved_at,active_flag,
  row_version,created_at,updated_at
FROM kb.document
"""


class KnowledgeDocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, tenant_id: UUID, document_id: UUID, *, lock: bool = False
    ) -> DocumentRecord | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            await self._session.execute(
                text(
                    _DOCUMENT + " WHERE document_id=:document_id "
                    "AND (tenant_id=:tenant_id OR tenant_id IS NULL)" + suffix
                ),
                {"tenant_id": tenant_id, "document_id": document_id},
            )
        ).one_or_none()
        return DocumentRecord(*tuple(row)) if row is not None else None

    async def versions(self, document_id: UUID) -> list[VersionRecord]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT document_version_id,version_number,sha256_checksum,content_type,
                      extraction_status,validation_status,current_version_flag,
                      published_processing_version_id,acquired_at,published_at,retired_at
                    FROM kb.document_version WHERE document_id=:document_id
                    ORDER BY version_number DESC,document_version_id
                """),
                {"document_id": document_id},
            )
        ).all()
        return [VersionRecord(*tuple(row)) for row in rows]

    async def processing_versions(self, document_id: UUID) -> list[ProcessingRecord]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT processing_version_id,document_version_id,processing_number,
                      parser_name,parser_version,chunker_name,chunker_version,
                      chunking_configuration_hash,embedding_model_code,processing_status,
                      validation_status,validation_json,chunk_count,embedded_chunk_count,
                      created_at,completed_at
                    FROM kb.document_processing_version WHERE document_id=:document_id
                    ORDER BY processing_number DESC,processing_version_id
                """),
                {"document_id": document_id},
            )
        ).all()
        return [
            ProcessingRecord(
                processing_version_id=row.processing_version_id,
                document_version_id=row.document_version_id,
                processing_number=row.processing_number,
                parser_name=row.parser_name,
                parser_version=row.parser_version,
                chunker_name=row.chunker_name,
                chunker_version=row.chunker_version,
                chunking_configuration_hash=row.chunking_configuration_hash,
                embedding_model_code=row.embedding_model_code,
                processing_status=row.processing_status,
                validation_status=row.validation_status,
                validation_json=cast("dict[str, object]", row.validation_json),
                chunk_count=row.chunk_count,
                embedded_chunk_count=row.embedded_chunk_count,
                created_at=row.created_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]

    async def approve(
        self,
        tenant_id: UUID,
        document_id: UUID,
        actor_id: UUID,
        decision: str,
        expected_version: int,
    ) -> bool:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                text("""
                    UPDATE kb.document SET approval_status=CAST(:decision AS varchar),
                      approved_by=CASE WHEN CAST(:decision AS varchar)='APPROVED'
                        THEN :actor_id END,
                      approved_at=CASE WHEN CAST(:decision AS varchar)='APPROVED'
                        THEN now() END,
                      row_version=row_version+1
                    WHERE document_id=:document_id
                      AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                      AND row_version=:expected_version AND approval_status<>'RETIRED'
                """),
                {
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "actor_id": actor_id,
                    "decision": decision,
                    "expected_version": expected_version,
                },
            ),
        )
        return result.rowcount == 1

    async def publication_candidate(
        self, document_id: UUID, processing_id: UUID
    ) -> tuple[UUID, str, str, int, int, str, str, str] | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT p.document_version_id,p.processing_status,p.validation_status,
                      coalesce(p.chunk_count,0),coalesce(p.embedded_chunk_count,0),
                      p.parser_name || '/' || p.parser_version,
                      p.chunker_name || '/' || p.chunker_version,p.embedding_model_code
                    FROM kb.document_processing_version p
                    WHERE p.document_id=:document_id
                      AND p.processing_version_id=:processing_id
                """),
                {"document_id": document_id, "processing_id": processing_id},
            )
        ).one_or_none()
        return cast(
            "tuple[UUID, str, str, int, int, str, str, str] | None", tuple(row) if row else None
        )

    async def lineage_evidence(
        self, document: DocumentRecord, processing_id: UUID
    ) -> tuple[int, int, bool, list[dict[str, str]]]:
        counts = (
            await self._session.execute(
                text("""
                    SELECT count(*) AS chunks,count(embedding.chunk_id) AS embeddings,
                      coalesce(bool_and(chunk.document_id=:document_id
                        AND chunk.source_id=:source_id
                        AND chunk.audience_code=:audience
                        AND chunk.security_classification=:classification),false) AS valid
                    FROM kb.document_chunk chunk
                    LEFT JOIN kb.chunk_embedding_1536 embedding
                      ON embedding.chunk_id=chunk.chunk_id
                    WHERE chunk.processing_version_id=:processing_id
                """),
                {
                    "processing_id": processing_id,
                    "document_id": document.document_id,
                    "source_id": document.source_id,
                    "audience": document.audience_code,
                    "classification": document.security_classification,
                },
            )
        ).one()
        permissions = (
            await self._session.execute(
                text("""
                    SELECT principal_type,principal_code,permission_code
                    FROM kb.document_permission WHERE document_id=:document_id
                    ORDER BY principal_type,principal_code,permission_code
                """),
                {"document_id": document.document_id},
            )
        ).all()
        return (
            int(counts.chunks),
            int(counts.embeddings),
            bool(counts.valid),
            [
                {
                    "principal_type": row.principal_type,
                    "principal_code": row.principal_code,
                    "permission_code": row.permission_code,
                }
                for row in permissions
            ],
        )

    async def publish(
        self,
        document: DocumentRecord,
        document_version_id: UUID,
        processing_id: UUID,
        actor_id: UUID,
        evidence: dict[str, object],
        correlation_id: str,
        request_id: str,
        deduplication_key: str,
    ) -> UUID | None:
        previous = await self._session.scalar(
            text("""
                SELECT document_version_id FROM kb.document_version
                WHERE document_id=:document_id AND current_version_flag FOR UPDATE
            """),
            {"document_id": document.document_id},
        )
        await self._session.execute(
            text("""
                UPDATE kb.document_version SET current_version_flag=false,retired_at=now()
                WHERE document_id=:document_id AND current_version_flag
                  AND document_version_id<>:version_id
            """),
            {"document_id": document.document_id, "version_id": document_version_id},
        )
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                text("""
                    UPDATE kb.document_version SET current_version_flag=true,
                      published_processing_version_id=:processing_id,published_at=now(),
                      retired_at=NULL
                    WHERE document_id=:document_id AND document_version_id=:version_id
                      AND extraction_status='COMPLETED'
                      AND validation_status IN ('PASSED','WARNING')
                """),
                {
                    "document_id": document.document_id,
                    "version_id": document_version_id,
                    "processing_id": processing_id,
                },
            ),
        )
        if result.rowcount != 1:
            return None
        await self._session.execute(
            text("""
                UPDATE kb.document SET row_version=row_version+1
                WHERE document_id=:document_id
            """),
            {"document_id": document.document_id},
        )
        await self._session.execute(
            text("""
                UPDATE kb.ingestion_run_item SET item_status='PUBLISHED',
                  pipeline_stage='COMPLETE',completed_at=now(),locked_at=NULL,locked_by=NULL,
                  row_version=row_version+1
                WHERE document_version_id=:version_id AND tenant_id=:tenant_id
            """),
            {"version_id": document_version_id, "tenant_id": evidence["tenant_id"]},
        )
        await self._publication_event(
            document,
            document_version_id,
            processing_id,
            "PUBLISHED",
            actor_id,
            cast("UUID | None", previous),
            evidence,
            correlation_id,
            request_id,
            deduplication_key,
        )
        return cast("UUID | None", previous)

    async def retire(
        self,
        document: DocumentRecord,
        actor_id: UUID,
        evidence: dict[str, object],
        correlation_id: str,
        request_id: str,
        deduplication_key: str,
    ) -> bool:
        current = (
            await self._session.execute(
                text("""
                    SELECT document_version_id,published_processing_version_id
                    FROM kb.document_version WHERE document_id=:document_id
                      AND current_version_flag FOR UPDATE
                """),
                {"document_id": document.document_id},
            )
        ).one_or_none()
        if current is None or current.published_processing_version_id is None:
            return False
        await self._session.execute(
            text("""
                UPDATE kb.document SET approval_status='RETIRED',active_flag=false,
                  row_version=row_version+1 WHERE document_id=:document_id
            """),
            {"document_id": document.document_id},
        )
        await self._session.execute(
            text("""
                UPDATE kb.document_version SET current_version_flag=false,retired_at=now()
                WHERE document_version_id=:version_id
            """),
            {"version_id": current.document_version_id},
        )
        await self._publication_event(
            document,
            current.document_version_id,
            current.published_processing_version_id,
            "RETIRED",
            actor_id,
            current.document_version_id,
            evidence,
            correlation_id,
            request_id,
            deduplication_key,
        )
        return True

    async def audit(
        self,
        tenant_id: UUID | None,
        actor_id: UUID,
        document_id: UUID,
        action: str,
        summary: dict[str, object],
        correlation_id: str,
        request_id: str,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_id AS varchar),'USER',:action,
                  'KNOWLEDGE_DOCUMENT',CAST(:document_id AS varchar),CAST(:summary AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_id": actor_id,
                "document_id": document_id,
                "action": action,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

    async def _publication_event(
        self,
        document: DocumentRecord,
        document_version_id: UUID,
        processing_id: UUID,
        action: str,
        actor_id: UUID,
        previous_version_id: UUID | None,
        evidence: dict[str, object],
        correlation_id: str,
        request_id: str,
        deduplication_key: str,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO kb.document_publication_event(
                  tenant_id,document_id,document_version_id,processing_version_id,
                  action_code,actor_user_id,previous_document_version_id,evidence_json,
                  correlation_id,request_id,deduplication_key)
                VALUES (:tenant_id,:document_id,:version_id,:processing_id,:action,
                  :actor_id,:previous_version_id,CAST(:evidence AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,:deduplication_key)
            """),
            {
                "tenant_id": evidence["tenant_id"],
                "document_id": document.document_id,
                "version_id": document_version_id,
                "processing_id": processing_id,
                "action": action,
                "actor_id": actor_id,
                "previous_version_id": previous_version_id,
                "evidence": json.dumps(evidence),
                "correlation_id": correlation_id,
                "request_id": request_id,
                "deduplication_key": deduplication_key,
            },
        )
