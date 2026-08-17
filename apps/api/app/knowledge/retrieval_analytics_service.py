"""Read-only retrieval quality analytics for knowledge administrators."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.retrieval_analytics_repository import RetrievalAnalyticsRepository
from apps.api.app.knowledge.retrieval_analytics_schemas import (
    RetrievalAnalyticsGroupKind,
    RetrievalAnalyticsSummaryResponse,
    RetrievalQueryGroupListResponse,
    RetrievalQueryGroupResponse,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class RetrievalAnalyticsService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._threshold = settings.retrieval_low_confidence_threshold

    async def summary(
        self, context: RequestContext, *, window_days: int
    ) -> RetrievalAnalyticsSummaryResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            row = await RetrievalAnalyticsRepository(uow.session).summary(
                tenant_id, window_days=window_days, threshold=self._threshold
            )
        event_count = int(row.event_count)
        zero_result_count = int(row.zero_result_count)
        low_confidence_count = int(row.low_confidence_count)
        return RetrievalAnalyticsSummaryResponse(
            window_days=window_days,
            low_confidence_threshold=self._threshold,
            event_count=event_count,
            zero_result_count=zero_result_count,
            zero_result_rate=_rate(zero_result_count, event_count),
            low_confidence_count=low_confidence_count,
            low_confidence_rate=_rate(low_confidence_count, event_count),
            query_group_count=int(row.query_group_count),
        )

    async def zero_result_groups(
        self, context: RequestContext, *, window_days: int, limit: int, offset: int
    ) -> RetrievalQueryGroupListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await RetrievalAnalyticsRepository(uow.session).zero_result_groups(
                tenant_id,
                window_days=window_days,
                threshold=self._threshold,
                limit=limit + 1,
                offset=offset,
            )
        return self._listing("ZERO_RESULT", rows, window_days=window_days, limit=limit)

    async def low_confidence_groups(
        self, context: RequestContext, *, window_days: int, limit: int, offset: int
    ) -> RetrievalQueryGroupListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await RetrievalAnalyticsRepository(uow.session).low_confidence_groups(
                tenant_id,
                window_days=window_days,
                threshold=self._threshold,
                limit=limit + 1,
                offset=offset,
            )
        return self._listing("LOW_CONFIDENCE", rows, window_days=window_days, limit=limit)

    def _listing(
        self,
        kind: RetrievalAnalyticsGroupKind,
        rows: list[Any],
        *,
        window_days: int,
        limit: int,
    ) -> RetrievalQueryGroupListResponse:
        return RetrievalQueryGroupListResponse(
            window_days=window_days,
            low_confidence_threshold=self._threshold,
            items=[_group(kind, row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )

    def _tenant(self, context: RequestContext) -> UUID:
        if not self._authorization.is_allowed(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN):
            raise AuthorizationError()
        if context.tenant_id is None or context.user_id is None:
            raise AuthorizationError()
        return context.tenant_id


def _rate(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def _group(kind: RetrievalAnalyticsGroupKind, row: Any) -> RetrievalQueryGroupResponse:
    return RetrievalQueryGroupResponse(
        kind=kind,
        normalized_query=row.normalized_query,
        event_count=int(row.event_count),
        matching_count=int(row.matching_count),
        best_top_score=float(row.best_top_score) if row.best_top_score is not None else None,
        surfaces=sorted(row.surfaces),
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        last_corpus_version_id=row.last_corpus_version_id,
    )
