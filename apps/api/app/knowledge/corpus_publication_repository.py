"""Set-based, tenant-scoped corpus publication persistence."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.knowledge.corpus_publication_models import (
    CorpusPublicationEvent,
    CorpusVersion,
    PublicationReadiness,
)

_VERSION_SELECT = """
SELECT corpus_version_id,tenant_id,version_number,validation_run_id,published_by,
  published_at,document_count,chunk_count,suppressed_chunk_count,active_flag,
  row_version,created_at
FROM kb.corpus_version
"""

# The publishable corpus mirrors the Task 13.3 validation scope: current
# versions of active tenant and global documents with their latest processing
# versions. Staleness compares processing activity against the run start.
_STALENESS_SQL = """
SELECT count(*) FROM kb.document_processing_version processing
JOIN kb.document document ON document.document_id=processing.document_id
WHERE (document.tenant_id=:tenant_id OR document.tenant_id IS NULL)
  AND document.active_flag
  AND processing.created_at>:run_started_at
"""


class CorpusPublicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def readiness(self, tenant_id: UUID) -> PublicationReadiness:
        run = (
            await self._session.execute(
                text("""
                    SELECT run_id,run_status,truncated_flag,started_at
                    FROM kb.corpus_validation_run
                    WHERE tenant_id=:tenant_id
                    ORDER BY created_at DESC,run_id DESC LIMIT 1
                """),
                {"tenant_id": tenant_id},
            )
        ).one_or_none()
        if run is None:
            return PublicationReadiness(
                validation_run_id=None,
                run_completed=False,
                truncated=False,
                stale=False,
                suppression_flagged_chunks=0,
            )
        stale = (
            int(
                await self._session.scalar(
                    text(_STALENESS_SQL),
                    {"tenant_id": tenant_id, "run_started_at": run.started_at},
                )
                or 0
            )
            > 0
        )
        flagged = int(
            await self._session.scalar(
                text(
                    "SELECT count(*) FROM kb.document_chunk "
                    "WHERE tenant_id=:tenant_id AND near_duplicate_suppressed_flag"
                ),
                {"tenant_id": tenant_id},
            )
            or 0
        )
        return PublicationReadiness(
            validation_run_id=run.run_id,
            run_completed=run.run_status == "COMPLETED",
            truncated=bool(run.truncated_flag),
            stale=stale,
            suppression_flagged_chunks=flagged,
        )

    async def active_version(self, tenant_id: UUID) -> CorpusVersion | None:
        row = (
            await self._session.execute(
                text(_VERSION_SELECT + "WHERE tenant_id=:tenant_id AND active_flag"),
                {"tenant_id": tenant_id},
            )
        ).one_or_none()
        return CorpusVersion(*tuple(row)) if row is not None else None

    async def version(self, tenant_id: UUID, corpus_version_id: UUID) -> CorpusVersion | None:
        row = (
            await self._session.execute(
                text(
                    _VERSION_SELECT
                    + "WHERE tenant_id=:tenant_id AND corpus_version_id=:corpus_version_id"
                ),
                {"tenant_id": tenant_id, "corpus_version_id": corpus_version_id},
            )
        ).one_or_none()
        return CorpusVersion(*tuple(row)) if row is not None else None

    async def previous_version(
        self, tenant_id: UUID, before_version_number: int
    ) -> CorpusVersion | None:
        row = (
            await self._session.execute(
                text(
                    _VERSION_SELECT
                    + """
                    WHERE tenant_id=:tenant_id AND version_number<:before_version_number
                    ORDER BY version_number DESC LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "before_version_number": before_version_number},
            )
        ).one_or_none()
        return CorpusVersion(*tuple(row)) if row is not None else None

    async def deactivate_active(self, tenant_id: UUID) -> UUID | None:
        result: Any = await self._session.execute(
            text("""
                UPDATE kb.corpus_version
                SET active_flag=false,row_version=row_version+1
                WHERE tenant_id=:tenant_id AND active_flag
                RETURNING corpus_version_id
            """),
            {"tenant_id": tenant_id},
        )
        row = result.one_or_none()
        return row.corpus_version_id if row is not None else None

    async def insert_version(
        self,
        corpus_version_id: UUID,
        tenant_id: UUID,
        validation_run_id: UUID,
        actor_user_id: UUID,
        *,
        document_count: int,
        chunk_count: int,
    ) -> int:
        version_number = int(
            await self._session.scalar(
                text(
                    "SELECT coalesce(max(version_number),0)+1 FROM kb.corpus_version "
                    "WHERE tenant_id=:tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
            or 1
        )
        await self._session.execute(
            text("""
                INSERT INTO kb.corpus_version(
                  corpus_version_id,tenant_id,version_number,validation_run_id,
                  published_by,document_count,chunk_count,suppressed_chunk_count,
                  active_flag)
                VALUES (:corpus_version_id,:tenant_id,:version_number,:validation_run_id,
                  :actor_user_id,:document_count,:chunk_count,0,true)
            """),
            {
                "corpus_version_id": corpus_version_id,
                "tenant_id": tenant_id,
                "version_number": version_number,
                "validation_run_id": validation_run_id,
                "actor_user_id": actor_user_id,
                "document_count": document_count,
                "chunk_count": chunk_count,
            },
        )
        return version_number

    async def snapshot_suppressed_chunks(self, corpus_version_id: UUID, tenant_id: UUID) -> int:
        result: Any = await self._session.execute(
            text("""
                INSERT INTO kb.corpus_version_suppressed_chunk(
                  corpus_version_id,tenant_id,chunk_id)
                SELECT :corpus_version_id,:tenant_id,chunk_id
                FROM kb.document_chunk
                WHERE tenant_id=:tenant_id AND near_duplicate_suppressed_flag
            """),
            {"corpus_version_id": corpus_version_id, "tenant_id": tenant_id},
        )
        suppressed = int(result.rowcount or 0)
        await self._session.execute(
            text("""
                UPDATE kb.corpus_version
                SET suppressed_chunk_count=:suppressed
                WHERE corpus_version_id=:corpus_version_id AND tenant_id=:tenant_id
            """),
            {
                "suppressed": suppressed,
                "corpus_version_id": corpus_version_id,
                "tenant_id": tenant_id,
            },
        )
        return suppressed

    async def activate_version(self, tenant_id: UUID, corpus_version_id: UUID) -> None:
        await self._session.execute(
            text("""
                UPDATE kb.corpus_version
                SET active_flag=true,row_version=row_version+1
                WHERE tenant_id=:tenant_id AND corpus_version_id=:corpus_version_id
            """),
            {"tenant_id": tenant_id, "corpus_version_id": corpus_version_id},
        )

    async def corpus_counts(self, tenant_id: UUID) -> tuple[int, int]:
        row = (
            await self._session.execute(
                text("""
                    SELECT
                      (SELECT count(*) FROM kb.document document
                        WHERE document.active_flag
                          AND (document.tenant_id=:tenant_id OR document.tenant_id IS NULL))
                        AS documents,
                      (SELECT count(*) FROM kb.document_chunk chunk
                        WHERE chunk.tenant_id=:tenant_id) AS chunks
                """),
                {"tenant_id": tenant_id},
            )
        ).one()
        return int(row.documents), int(row.chunks)

    async def insert_event(
        self,
        tenant_id: UUID,
        action_code: str,
        corpus_version_id: UUID,
        previous_corpus_version_id: UUID | None,
        actor_user_id: UUID,
        evidence: dict[str, Any],
        correlation_id: str,
        request_id: str,
        deduplication_key: str,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO kb.corpus_publication_event(
                  tenant_id,action_code,corpus_version_id,previous_corpus_version_id,
                  actor_user_id,evidence_json,correlation_id,request_id,deduplication_key)
                VALUES (:tenant_id,:action_code,:corpus_version_id,
                  :previous_corpus_version_id,:actor_user_id,CAST(:evidence AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,:deduplication_key)
            """),
            {
                "tenant_id": tenant_id,
                "action_code": action_code,
                "corpus_version_id": corpus_version_id,
                "previous_corpus_version_id": previous_corpus_version_id,
                "actor_user_id": actor_user_id,
                "evidence": json.dumps(evidence),
                "correlation_id": correlation_id,
                "request_id": request_id,
                "deduplication_key": deduplication_key,
            },
        )

    async def versions(self, tenant_id: UUID, *, limit: int, offset: int) -> list[CorpusVersion]:
        rows = (
            await self._session.execute(
                text(
                    _VERSION_SELECT
                    + """
                    WHERE tenant_id=:tenant_id
                    ORDER BY version_number DESC LIMIT :limit OFFSET :offset
                    """
                ),
                {"tenant_id": tenant_id, "limit": limit, "offset": offset},
            )
        ).all()
        return [CorpusVersion(*tuple(row)) for row in rows]

    async def events(
        self, tenant_id: UUID, *, limit: int, offset: int
    ) -> list[CorpusPublicationEvent]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT event.publication_event_id,event.action_code,
                      version.version_number,previous_version.version_number,
                      event.actor_user_id,event.evidence_json,event.occurred_at
                    FROM kb.corpus_publication_event event
                    JOIN kb.corpus_version version
                      ON version.corpus_version_id=event.corpus_version_id
                    LEFT JOIN kb.corpus_version previous_version
                      ON previous_version.corpus_version_id=event.previous_corpus_version_id
                    WHERE event.tenant_id=:tenant_id
                    ORDER BY event.occurred_at DESC,event.publication_event_id DESC
                    LIMIT :limit OFFSET :offset
                """),
                {"tenant_id": tenant_id, "limit": limit, "offset": offset},
            )
        ).all()
        return [CorpusPublicationEvent(*tuple(row)) for row in rows]

    async def audit(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        action_code: str,
        corpus_version_id: UUID,
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
                  :action_code,'CORPUS_VERSION',CAST(:corpus_version_id AS varchar),
                  CAST(:summary AS jsonb),CAST(:correlation_id AS uuid),:request_id,
                  'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "action_code": action_code,
                "corpus_version_id": corpus_version_id,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
