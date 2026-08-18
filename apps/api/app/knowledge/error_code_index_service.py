"""Read-only chunk error-code index evidence for knowledge administrators."""

from collections.abc import Callable
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.error_code_index_repository import ErrorCodeIndexRepository
from apps.api.app.knowledge.error_code_index_schemas import (
    ErrorCodeIndexEntryResponse,
    ErrorCodeIndexListResponse,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class ErrorCodeIndexService:
    def __init__(self, factory: UnitOfWorkFactory, authorization: AuthorizationService) -> None:
        self._factory = factory
        self._authorization = authorization

    async def listing(
        self, context: RequestContext, *, prefix: str | None, limit: int, offset: int
    ) -> ErrorCodeIndexListResponse:
        tenant_id = self._tenant(context)
        # Stored codes are uppercase with dash separators; normalizing the
        # prefix the same way also removes the LIKE wildcard underscore.
        normalized_prefix = (
            prefix.strip().upper().replace(" ", "-").replace("_", "-") if prefix else None
        )
        async with self._factory(context) as uow:
            rows = await ErrorCodeIndexRepository(uow.session).listing(
                tenant_id, prefix=normalized_prefix, limit=limit + 1, offset=offset
            )
        return ErrorCodeIndexListResponse(
            items=[
                ErrorCodeIndexEntryResponse(
                    error_code=row.error_code,
                    indexed_chunk_count=int(row.indexed_chunk_count),
                    published_chunk_count=int(row.published_chunk_count),
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    def _tenant(self, context: RequestContext) -> UUID:
        if not self._authorization.is_allowed(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN):
            raise AuthorizationError()
        if context.tenant_id is None or context.user_id is None:
            raise AuthorizationError()
        return context.tenant_id
