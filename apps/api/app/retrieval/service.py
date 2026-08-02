"""Authorization and cancellation boundary for independent retrieval strategies."""

import asyncio
import math
from collections.abc import Callable

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ConflictError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.retrieval.models import (
    RetrievalCandidates,
    RetrievalFilters,
    RetrievalRequest,
)
from apps.api.app.retrieval.normalization import InvalidRetrievalQuery, normalize_query
from apps.api.app.retrieval.repository import (
    RetrievalPrincipal,
    RetrievalQueryTimeout,
    RetrievalRepository,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class RetrievalRequestError(ConflictError):
    error_code = "invalid_retrieval_request"


class RetrievalDeadlineExceeded(RuntimeError):
    """The bounded retrieval operation was cancelled before completion."""


class RetrievalService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._settings = settings

    async def search(
        self, context: RequestContext, request: RetrievalRequest
    ) -> RetrievalCandidates:
        principal = self._principal(context, request.persona)
        normalized_query = _query(request.query)
        embedding = _embedding(request.query_embedding)
        filters = _filters(request.filters)
        if not 1 <= request.limit <= self._settings.retrieval_max_results:
            raise RetrievalRequestError(
                f"Retrieval limit must be between 1 and {self._settings.retrieval_max_results}."
            )
        if not request.embedding_model_code or len(request.embedding_model_code) > 100:
            raise RetrievalRequestError("Embedding model code is invalid.")
        try:
            async with asyncio.timeout(self._settings.retrieval_timeout_seconds):
                async with self._factory(context) as uow:
                    repository = RetrievalRepository(
                        uow.session, self._settings.retrieval_statement_timeout_ms
                    )
                    lexical = await repository.lexical(
                        principal, normalized_query, filters, request.limit
                    )
                    vector = await repository.vector(
                        principal,
                        embedding,
                        request.embedding_model_code,
                        filters,
                        request.limit,
                    )
                    await uow.commit()
        except (TimeoutError, RetrievalQueryTimeout) as error:
            raise RetrievalDeadlineExceeded("Retrieval deadline exceeded") from error
        return RetrievalCandidates(
            normalized_query=normalized_query,
            embedding_model_code=request.embedding_model_code,
            lexical=lexical,
            vector=vector,
        )

    def _principal(self, context: RequestContext, persona: str) -> RetrievalPrincipal:
        if context.tenant_id is None or context.user_id is None:
            raise AuthorizationError("Authenticated retrieval identity is required.")
        normalized_persona = persona.strip().upper()
        if normalized_persona not in {"EMPLOYEE", "ANALYST"}:
            raise RetrievalRequestError("Retrieval persona is invalid.")
        permission = (
            Permission.KNOWLEDGE_READ_ANALYST
            if normalized_persona == "ANALYST"
            else Permission.KNOWLEDGE_READ_EMPLOYEE
        )
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError("Knowledge retrieval is not authorized.")
        audiences = (
            ("ALL", "EMPLOYEE", "ANALYST", "TECHNICAL_SPECIALIST")
            if normalized_persona == "ANALYST"
            else ("ALL", "EMPLOYEE")
        )
        levels = (
            ("PUBLIC", "INTERNAL", "CONFIDENTIAL")
            if normalized_persona == "ANALYST"
            else ("PUBLIC", "INTERNAL")
        )
        if "PLATFORM_ADMIN" in context.roles:
            audiences = (*audiences, "ADMIN")
            levels = (*levels, "RESTRICTED")
        return RetrievalPrincipal(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            role_codes=tuple(sorted(context.roles)),
            support_group_codes=tuple(sorted(str(value) for value in context.support_group_ids)),
            business_unit_code=(
                str(context.business_unit_id) if context.business_unit_id is not None else None
            ),
            audience_codes=audiences,
            security_levels=levels,
            persona=normalized_persona,
        )


def _query(value: str) -> str:
    try:
        return normalize_query(value)
    except InvalidRetrievalQuery as error:
        raise RetrievalRequestError(str(error) + ".") from error


def _embedding(values: tuple[float, ...]) -> tuple[float, ...]:
    if len(values) != 1536 or any(not math.isfinite(value) for value in values):
        raise RetrievalRequestError("Query embedding must contain 1536 finite values.")
    return values


def _filters(filters: RetrievalFilters) -> RetrievalFilters:
    return RetrievalFilters(
        product_codes=_codes(filters.product_codes, "product"),
        module_codes=_codes(filters.module_codes, "module"),
        release_families=_codes(filters.release_families, "release family"),
        release_codes=_codes(filters.release_codes, "release"),
        language_codes=tuple(sorted({value.strip().lower() for value in filters.language_codes})),
        source_ids=tuple(sorted(set(filters.source_ids), key=str)),
    )


def _codes(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(sorted({value.strip().upper() for value in values if value.strip()}))
    if len(normalized) > 20 or any(len(value) > 150 for value in normalized):
        raise RetrievalRequestError(f"Too many or invalid {label} filters.")
    return normalized
