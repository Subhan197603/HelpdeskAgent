"""Authorization and cancellation boundary for independent retrieval strategies."""

import asyncio
import math
from collections.abc import Callable
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ConflictError, ExternalDependencyError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.retrieval.fusion import fuse_candidates
from apps.api.app.retrieval.models import (
    RetrievalCandidates,
    RetrievalConfiguration,
    RetrievalEvidenceSet,
    RetrievalFilters,
    RetrievalRequest,
)
from apps.api.app.retrieval.normalization import InvalidRetrievalQuery, normalize_query
from apps.api.app.retrieval.providers import (
    DeterministicQueryEmbeddingProvider,
    QueryEmbeddingProvider,
    RerankingProvider,
    RetrievalProviderError,
)
from apps.api.app.retrieval.repository import (
    RetrievalPrincipal,
    RetrievalQueryTimeout,
    RetrievalRepository,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class RetrievalRequestError(ConflictError):
    error_code = "invalid_retrieval_request"


class RetrievalDeadlineExceeded(ExternalDependencyError):
    """The bounded retrieval operation was cancelled before completion."""

    error_code = "retrieval_deadline_exceeded"


class RetrievalService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        settings: Settings,
        embeddings: QueryEmbeddingProvider | None = None,
        reranker: RerankingProvider | None = None,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._settings = settings
        self._embeddings = embeddings or DeterministicQueryEmbeddingProvider(
            settings.retrieval_embedding_model_code
        )
        self._reranker = reranker

    async def evidence(
        self,
        context: RequestContext,
        *,
        query: str,
        filters: RetrievalFilters,
        limit: int,
        persona: str,
    ) -> RetrievalEvidenceSet:
        self._principal(context, persona)
        normalized_query = _query(query)
        normalized_filters = _filters(filters)
        try:
            embedding = await self._embeddings.embed(normalized_query)
            candidates = await self.search(
                context,
                RetrievalRequest(
                    query=normalized_query,
                    query_embedding=embedding,
                    filters=normalized_filters,
                    limit=limit,
                    persona=persona,
                    embedding_model_code=self._embeddings.model_code,
                ),
            )
            configuration = await self._configuration(context)
            authorized = tuple(
                {item.chunk_id: item for item in (*candidates.lexical, *candidates.vector)}.values()
            )
            rerank_scores: dict[UUID, float] | None = None
            if configuration.reranking_enabled:
                if self._reranker is None:
                    raise ExternalDependencyError("Approved reranking is not configured.")
                rerank_scores = await self._reranker.rerank(normalized_query, authorized)
        except RetrievalProviderError as error:
            raise ExternalDependencyError("Retrieval provider is unavailable.") from error
        except RetrievalQueryTimeout as error:
            raise RetrievalDeadlineExceeded("Retrieval deadline exceeded.") from error
        evidence = fuse_candidates(
            normalized_query,
            candidates.lexical,
            candidates.vector,
            normalized_filters,
            configuration,
            rerank_scores,
            limit=limit,
        )
        return RetrievalEvidenceSet(
            normalized_query=normalized_query,
            retrieval_configuration_version_id=configuration.version_id,
            evidence=evidence,
        )

    async def _configuration(self, context: RequestContext) -> RetrievalConfiguration:
        if context.tenant_id is None:
            raise AuthorizationError("Authenticated retrieval identity is required.")
        async with self._factory(context) as uow:
            repository = RetrievalRepository(
                uow.session, self._settings.retrieval_statement_timeout_ms
            )
            configuration = await repository.configuration(context.tenant_id)
            await uow.commit()
        if configuration is None:
            raise ExternalDependencyError("Published retrieval configuration is unavailable.")
        return configuration

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
