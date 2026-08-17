"""Set-based, tenant-scoped aggregation over retrieval query events."""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_WINDOW_FILTER = """
WHERE tenant_id=:tenant_id
  AND captured_at>=now()-make_interval(days => :window_days)
"""

_SUMMARY_SQL = f"""
SELECT count(*) AS event_count,
  count(*) FILTER (WHERE zero_result_flag) AS zero_result_count,
  count(*) FILTER (
    WHERE NOT zero_result_flag AND top_score<:threshold
  ) AS low_confidence_count,
  count(DISTINCT normalized_query) AS query_group_count
FROM kb.retrieval_query_event
{_WINDOW_FILTER}
"""

# Groups are keyed by the bounded normalized query; the trailing aggregates
# give the Task 14.2 screens their counts, trends, and last-seen evidence.
_GROUP_SQL_TEMPLATE = f"""
SELECT normalized_query,
  count(*) AS event_count,
  count(*) FILTER (WHERE {{matching}}) AS matching_count,
  max(top_score) AS best_top_score,
  array_agg(DISTINCT surface) AS surfaces,
  min(captured_at) AS first_seen_at,
  max(captured_at) AS last_seen_at,
  (array_agg(corpus_version_id ORDER BY captured_at DESC,event_id DESC))[1]
    AS last_corpus_version_id
FROM kb.retrieval_query_event
{_WINDOW_FILTER}
GROUP BY normalized_query
HAVING count(*) FILTER (WHERE {{matching}})>0
ORDER BY matching_count DESC,last_seen_at DESC,normalized_query
LIMIT :limit OFFSET :offset
"""

_ZERO_RESULT_MATCH = "zero_result_flag"
_LOW_CONFIDENCE_MATCH = "NOT zero_result_flag AND top_score<:threshold"


class RetrievalAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def summary(self, tenant_id: UUID, *, window_days: int, threshold: float) -> Any:
        return (
            await self._session.execute(
                text(_SUMMARY_SQL),
                {"tenant_id": tenant_id, "window_days": window_days, "threshold": threshold},
            )
        ).one()

    async def zero_result_groups(
        self, tenant_id: UUID, *, window_days: int, threshold: float, limit: int, offset: int
    ) -> list[Any]:
        return await self._groups(
            _ZERO_RESULT_MATCH,
            tenant_id,
            window_days=window_days,
            threshold=threshold,
            limit=limit,
            offset=offset,
        )

    async def low_confidence_groups(
        self, tenant_id: UUID, *, window_days: int, threshold: float, limit: int, offset: int
    ) -> list[Any]:
        return await self._groups(
            _LOW_CONFIDENCE_MATCH,
            tenant_id,
            window_days=window_days,
            threshold=threshold,
            limit=limit,
            offset=offset,
        )

    async def _groups(
        self,
        matching: str,
        tenant_id: UUID,
        *,
        window_days: int,
        threshold: float,
        limit: int,
        offset: int,
    ) -> list[Any]:
        statement = _GROUP_SQL_TEMPLATE.format(matching=matching)
        parameters: dict[str, object] = {
            "tenant_id": tenant_id,
            "window_days": window_days,
            "limit": limit,
            "offset": offset,
        }
        if ":threshold" in statement:
            parameters["threshold"] = threshold
        rows = await self._session.execute(text(statement), parameters)
        return list(rows)
