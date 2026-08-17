"""Append-only observational capture of retrieval query events."""

from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

RetrievalSurface = Literal["EVIDENCE_SEARCH", "EMPLOYEE_AGENT", "ANALYST_COPILOT"]

# The active corpus version is resolved inside the insert so the event records
# exactly what was searchable when the query ran; without an active
# publication the reference stays NULL.
_INSERT_SQL = """
INSERT INTO kb.retrieval_query_event (
  tenant_id,surface,normalized_query,result_count,zero_result_flag,top_score,
  corpus_version_id
)
SELECT :tenant_id,:surface,:normalized_query,:result_count,:zero_result_flag,
  :top_score,
  (SELECT corpus_version_id FROM kb.corpus_version
   WHERE tenant_id=:tenant_id AND active_flag)
"""

_RETENTION_SQL = """
DELETE FROM kb.retrieval_query_event
WHERE tenant_id=:tenant_id
  AND captured_at<now()-make_interval(days => :retention_days)
"""


class RetrievalQueryEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_event(
        self,
        *,
        tenant_id: UUID,
        surface: RetrievalSurface,
        normalized_query: str,
        result_count: int,
        top_score: float | None,
    ) -> None:
        await self._session.execute(
            text(_INSERT_SQL),
            {
                "tenant_id": tenant_id,
                "surface": surface,
                "normalized_query": normalized_query,
                "result_count": result_count,
                "zero_result_flag": result_count == 0,
                "top_score": top_score,
            },
        )

    async def enforce_retention(self, *, tenant_id: UUID, retention_days: int) -> None:
        await self._session.execute(
            text(_RETENTION_SQL),
            {"tenant_id": tenant_id, "retention_days": retention_days},
        )
