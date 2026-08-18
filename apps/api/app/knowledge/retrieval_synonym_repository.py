"""Tenant-scoped persistence for the synonym and acronym registry."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = """
synonym_id,term,expansion,synonym_status,synonym_note,decided_at,row_version
"""

_LIST_SQL = f"""
SELECT {_COLUMNS}
FROM kb.retrieval_synonym
WHERE tenant_id=:tenant_id
  AND (CAST(:status AS varchar) IS NULL OR synonym_status=:status)
  AND (CAST(:term AS varchar) IS NULL OR term LIKE :term || '%')
ORDER BY term,expansion
LIMIT :limit OFFSET :offset
"""

_PAIR_SELECT = f"""
SELECT {_COLUMNS}
FROM kb.retrieval_synonym
WHERE tenant_id=:tenant_id AND term=:term AND expansion=:expansion
"""


class RetrievalSynonymRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_entries(
        self,
        tenant_id: UUID,
        *,
        status: str | None,
        term: str | None,
        limit: int,
        offset: int,
    ) -> list[Any]:
        rows = await self._session.execute(
            text(_LIST_SQL),
            {
                "tenant_id": tenant_id,
                "status": status,
                "term": term,
                "limit": limit,
                "offset": offset,
            },
        )
        return list(rows)

    async def entry(self, tenant_id: UUID, term: str, expansion: str) -> Any:
        return (
            await self._session.execute(
                text(_PAIR_SELECT),
                {"tenant_id": tenant_id, "term": term, "expansion": expansion},
            )
        ).one_or_none()

    async def active_expansion_count(self, tenant_id: UUID, term: str) -> int:
        return int(
            (
                await self._session.execute(
                    text("""
                        SELECT count(*) FROM kb.retrieval_synonym
                        WHERE tenant_id=:tenant_id AND term=:term
                          AND synonym_status<>'RETIRED'
                    """),
                    {"tenant_id": tenant_id, "term": term},
                )
            ).scalar_one()
        )

    async def insert_entry(
        self,
        tenant_id: UUID,
        *,
        term: str,
        expansion: str,
        status: str,
        note: str | None,
        decided_by: UUID,
    ) -> Any:
        return (
            await self._session.execute(
                text(f"""
                    INSERT INTO kb.retrieval_synonym (
                      tenant_id,term,expansion,synonym_status,synonym_note,decided_by
                    )
                    VALUES (:tenant_id,:term,:expansion,:status,:note,:decided_by)
                    ON CONFLICT (tenant_id,term,expansion) DO NOTHING
                    RETURNING {_COLUMNS}
                """),
                {
                    "tenant_id": tenant_id,
                    "term": term,
                    "expansion": expansion,
                    "status": status,
                    "note": note,
                    "decided_by": decided_by,
                },
            )
        ).one_or_none()

    async def update_entry(
        self,
        tenant_id: UUID,
        *,
        term: str,
        expansion: str,
        status: str,
        note: str | None,
        decided_by: UUID,
        expected_row_version: int,
    ) -> Any:
        return (
            await self._session.execute(
                text(f"""
                    UPDATE kb.retrieval_synonym
                    SET synonym_status=:status,synonym_note=:note,
                      decided_by=:decided_by,decided_at=now(),
                      row_version=row_version+1
                    WHERE tenant_id=:tenant_id AND term=:term
                      AND expansion=:expansion
                      AND row_version=:expected_row_version
                    RETURNING {_COLUMNS}
                """),
                {
                    "tenant_id": tenant_id,
                    "term": term,
                    "expansion": expansion,
                    "status": status,
                    "note": note,
                    "decided_by": decided_by,
                    "expected_row_version": expected_row_version,
                },
            )
        ).one_or_none()

    async def audit_entry(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        synonym_id: UUID,
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
                  'KNOWLEDGE_SYNONYM_CHANGE','KNOWLEDGE_SYNONYM',
                  CAST(:synonym_id AS varchar),CAST(:summary AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "synonym_id": synonym_id,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
