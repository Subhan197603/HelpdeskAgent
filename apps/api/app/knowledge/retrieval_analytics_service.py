"""Retrieval quality analytics and audited gap dispositions."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ConflictError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.corpus_validation_service import (
    _hash,
    _identity,
    _validate_claim,
)
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.retrieval_analytics_repository import RetrievalAnalyticsRepository
from apps.api.app.knowledge.retrieval_analytics_schemas import (
    KnowledgeGapDispositionCommand,
    KnowledgeGapDispositionResponse,
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
        expansion_applied_count = int(row.expansion_applied_count)
        return RetrievalAnalyticsSummaryResponse(
            window_days=window_days,
            low_confidence_threshold=self._threshold,
            event_count=event_count,
            zero_result_count=zero_result_count,
            zero_result_rate=_rate(zero_result_count, event_count),
            low_confidence_count=low_confidence_count,
            low_confidence_rate=_rate(low_confidence_count, event_count),
            expansion_applied_count=expansion_applied_count,
            expansion_applied_rate=_rate(expansion_applied_count, event_count),
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

    async def disposition(
        self,
        context: RequestContext,
        command: KnowledgeGapDispositionCommand,
        idempotency_key: str,
    ) -> KnowledgeGapDispositionResponse:
        if not self._authorization.is_allowed(context, Permission.KNOWLEDGE_SOURCE_UPDATE):
            raise AuthorizationError()
        tenant_id, user_id = _identity(context)
        request_hash = _hash(
            "knowledge-gap-disposition",
            {
                "tenant_id": str(tenant_id),
                "normalized_query": command.normalized_query,
                "disposition_status": command.disposition_status,
                "disposition_note": command.disposition_note,
                "expected_row_version": command.expected_row_version,
            },
        )
        async with self._factory(context) as uow:
            sources = KnowledgeSourceRepository(uow.session)
            claim = await sources.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_GAP_DISPOSITION"
            )
            _validate_claim(claim, user_id, request_hash)
            repository = RetrievalAnalyticsRepository(uow.session)
            if claim.processing_status == "COMPLETED":
                row = await repository.disposition(tenant_id, command.normalized_query)
                if row is None:
                    raise ConflictError("Gap disposition result is unavailable.")
                await uow.commit()
                return _disposition_response(row, replayed=True)
            previous = await repository.disposition(tenant_id, command.normalized_query)
            if command.expected_row_version is None:
                if previous is not None:
                    raise ConflictError(
                        "Gap disposition already exists; supply expected_row_version."
                    )
                row = await repository.insert_disposition(
                    tenant_id,
                    normalized_query=command.normalized_query,
                    status=command.disposition_status,
                    note=command.disposition_note,
                    decided_by=user_id,
                )
            else:
                row = await repository.update_disposition(
                    tenant_id,
                    normalized_query=command.normalized_query,
                    status=command.disposition_status,
                    note=command.disposition_note,
                    decided_by=user_id,
                    expected_row_version=command.expected_row_version,
                )
            if row is None:
                raise ConflictError("Gap disposition was changed concurrently; reload and retry.")
            await repository.audit_disposition(
                tenant_id,
                user_id,
                row.disposition_id,
                {
                    "normalized_query": command.normalized_query,
                    "disposition_status": command.disposition_status,
                    "disposition_note": command.disposition_note,
                    "previous_status": (
                        previous.disposition_status if previous is not None else None
                    ),
                    "row_version": int(row.row_version),
                },
                context.correlation_id,
                context.request_id,
            )
            await sources.complete_idempotency(
                claim.record_id, "KNOWLEDGE_GAP", row.disposition_id, 201
            )
            await uow.commit()
        return _disposition_response(row, replayed=False)

    def _tenant(self, context: RequestContext) -> UUID:
        if not self._authorization.is_allowed(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN):
            raise AuthorizationError()
        if context.tenant_id is None or context.user_id is None:
            raise AuthorizationError()
        return context.tenant_id


def _rate(part: int, total: int) -> float:
    return round(part / total, 4) if total else 0.0


def _group(kind: RetrievalAnalyticsGroupKind, row: Any) -> RetrievalQueryGroupResponse:
    disposition = None
    if row.disposition_status is not None:
        disposition = KnowledgeGapDispositionResponse(
            disposition_status=row.disposition_status,
            disposition_note=row.disposition_note,
            decided_at=row.disposition_decided_at,
            row_version=int(row.disposition_row_version),
        )
    return RetrievalQueryGroupResponse(
        kind=kind,
        normalized_query=row.normalized_query,
        event_count=int(row.event_count),
        matching_count=int(row.matching_count),
        expanded_event_count=int(row.expanded_event_count),
        expanded_zero_result_count=int(row.expanded_zero_result_count),
        unexpanded_zero_result_count=int(row.unexpanded_zero_result_count),
        best_top_score=float(row.best_top_score) if row.best_top_score is not None else None,
        surfaces=sorted(row.surfaces),
        first_seen_at=row.first_seen_at,
        last_seen_at=row.last_seen_at,
        last_corpus_version_id=row.last_corpus_version_id,
        disposition=disposition,
    )


def _disposition_response(row: Any, *, replayed: bool) -> KnowledgeGapDispositionResponse:
    return KnowledgeGapDispositionResponse(
        disposition_status=row.disposition_status,
        disposition_note=row.disposition_note,
        decided_at=row.decided_at,
        row_version=int(row.row_version),
        replayed=replayed,
    )
