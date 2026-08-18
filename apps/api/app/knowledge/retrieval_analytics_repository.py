"""Set-based, tenant-scoped aggregation and gap dispositions for query events."""

import json
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
  count(*) FILTER (WHERE expansion_applied IS TRUE) AS expansion_applied_count,
  count(*) FILTER (
    WHERE error_code_matching_applied IS TRUE
  ) AS error_code_matched_count,
  count(DISTINCT normalized_query) AS query_group_count
FROM kb.retrieval_query_event
{_WINDOW_FILTER}
"""

# Groups are keyed by the bounded normalized query; the trailing aggregates
# give the Task 14.2 screens their counts, trends, and last-seen evidence, and
# the outer join attaches the current Task 14.3 disposition, if any.
_GROUP_SQL_TEMPLATE = f"""
SELECT grouped.*,
  disposition.disposition_status,
  disposition.disposition_note,
  disposition.decided_at AS disposition_decided_at,
  disposition.row_version AS disposition_row_version
FROM (
  SELECT normalized_query,
    count(*) AS event_count,
    count(*) FILTER (WHERE {{matching}}) AS matching_count,
    count(*) FILTER (WHERE expansion_applied IS TRUE) AS expanded_event_count,
    count(*) FILTER (
      WHERE expansion_applied IS TRUE AND zero_result_flag
    ) AS expanded_zero_result_count,
    count(*) FILTER (
      WHERE expansion_applied IS NOT TRUE AND zero_result_flag
    ) AS unexpanded_zero_result_count,
    count(*) FILTER (
      WHERE error_code_matching_applied IS TRUE
    ) AS matched_event_count,
    count(*) FILTER (
      WHERE error_code_matching_applied IS TRUE AND zero_result_flag
    ) AS matched_zero_result_count,
    count(*) FILTER (
      WHERE error_code_matching_applied IS NOT TRUE AND zero_result_flag
    ) AS unmatched_zero_result_count,
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
) AS grouped
LEFT JOIN kb.knowledge_gap_disposition disposition
  ON disposition.tenant_id=:tenant_id
  AND disposition.normalized_query=grouped.normalized_query
ORDER BY grouped.matching_count DESC,grouped.last_seen_at DESC,
  grouped.normalized_query
LIMIT :limit OFFSET :offset
"""

_DISPOSITION_SELECT = """
SELECT disposition_id,disposition_status,disposition_note,decided_at,row_version
FROM kb.knowledge_gap_disposition
WHERE tenant_id=:tenant_id AND normalized_query=:normalized_query
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

    async def disposition(self, tenant_id: UUID, normalized_query: str) -> Any:
        return (
            await self._session.execute(
                text(_DISPOSITION_SELECT),
                {"tenant_id": tenant_id, "normalized_query": normalized_query},
            )
        ).one_or_none()

    async def insert_disposition(
        self,
        tenant_id: UUID,
        *,
        normalized_query: str,
        status: str,
        note: str | None,
        decided_by: UUID,
    ) -> Any:
        return (
            await self._session.execute(
                text("""
                    INSERT INTO kb.knowledge_gap_disposition (
                      tenant_id,normalized_query,disposition_status,
                      disposition_note,decided_by
                    )
                    VALUES (:tenant_id,:normalized_query,:status,:note,:decided_by)
                    ON CONFLICT (tenant_id,normalized_query) DO NOTHING
                    RETURNING disposition_id,disposition_status,disposition_note,
                      decided_at,row_version
                """),
                {
                    "tenant_id": tenant_id,
                    "normalized_query": normalized_query,
                    "status": status,
                    "note": note,
                    "decided_by": decided_by,
                },
            )
        ).one_or_none()

    async def update_disposition(
        self,
        tenant_id: UUID,
        *,
        normalized_query: str,
        status: str,
        note: str | None,
        decided_by: UUID,
        expected_row_version: int,
    ) -> Any:
        return (
            await self._session.execute(
                text("""
                    UPDATE kb.knowledge_gap_disposition
                    SET disposition_status=:status,disposition_note=:note,
                      decided_by=:decided_by,decided_at=now(),
                      row_version=row_version+1
                    WHERE tenant_id=:tenant_id
                      AND normalized_query=:normalized_query
                      AND row_version=:expected_row_version
                    RETURNING disposition_id,disposition_status,disposition_note,
                      decided_at,row_version
                """),
                {
                    "tenant_id": tenant_id,
                    "normalized_query": normalized_query,
                    "status": status,
                    "note": note,
                    "decided_by": decided_by,
                    "expected_row_version": expected_row_version,
                },
            )
        ).one_or_none()

    async def audit_disposition(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        disposition_id: UUID,
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
                  'KNOWLEDGE_GAP_DISPOSITION','KNOWLEDGE_GAP',
                  CAST(:disposition_id AS varchar),CAST(:summary AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "disposition_id": disposition_id,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
