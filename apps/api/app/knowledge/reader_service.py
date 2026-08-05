"""Persona-authorized reading of the published knowledge corpus."""

from collections.abc import Callable
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import NotFoundError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.knowledge.reader_repository import KnowledgeReaderRepository
from apps.api.app.knowledge.reader_schemas import (
    KnowledgeArticleDetailResponse,
    KnowledgeArticleFacet,
    KnowledgeArticleListResponse,
    KnowledgeArticleSection,
    KnowledgeArticleSummary,
)
from apps.api.app.retrieval.service import resolve_knowledge_principal

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class KnowledgeReaderService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._settings = settings

    async def articles(
        self,
        context: RequestContext,
        *,
        persona: str,
        document_type: str | None,
        limit: int,
        offset: int,
    ) -> KnowledgeArticleListResponse:
        principal = resolve_knowledge_principal(self._authorization, context, persona)
        async with self._factory(context) as uow:
            repository = KnowledgeReaderRepository(uow.session)
            rows = await repository.articles(principal, document_type, limit + 1, offset)
            facets = await repository.facets(principal)
            await uow.commit()
        return KnowledgeArticleListResponse(
            items=[
                KnowledgeArticleSummary(
                    id=row.document_id,
                    title=row.title,
                    document_type=row.document_type,
                    source_type=row.source_type,
                    source_name=row.source_name,
                    excerpt=row.excerpt,
                    language_code=row.language_code,
                    product_name=row.product_name,
                    release_code=row.release_code,
                    audience_code=row.audience_code,
                    published_at=row.published_at,
                    updated_at=row.updated_at,
                )
                for row in rows[:limit]
            ],
            facets=[
                KnowledgeArticleFacet(document_type=facet.document_type, count=facet.count)
                for facet in facets
            ],
            has_more=len(rows) > limit,
        )

    async def article(
        self, context: RequestContext, *, persona: str, document_id: UUID
    ) -> KnowledgeArticleDetailResponse:
        principal = resolve_knowledge_principal(self._authorization, context, persona)
        async with self._factory(context) as uow:
            repository = KnowledgeReaderRepository(uow.session)
            row = await repository.article(principal, document_id)
            if row is None:
                raise NotFoundError("Knowledge article not found.")
            sections = await repository.sections(
                principal.tenant_id,
                row.document_version_id,
                row.published_processing_version_id,
            )
            await uow.commit()
        return KnowledgeArticleDetailResponse(
            id=row.document_id,
            title=row.title,
            document_type=row.document_type,
            source_type=row.source_type,
            source_name=row.source_name,
            audience_code=row.audience_code,
            security_classification=row.security_classification,
            language_code=row.language_code,
            product_name=row.product_name,
            release_code=row.release_code,
            canonical_url=row.canonical_url,
            owner_group_name=row.owner_group_name,
            policy_owner=row.policy_owner,
            process_owner=row.process_owner,
            version_number=row.version_number,
            published_at=row.published_at,
            updated_at=row.updated_at,
            next_review_date=row.next_review_date,
            sections=[
                KnowledgeArticleSection(
                    heading_path=section.heading_path,
                    section_title=section.section_title,
                    section_anchor=section.section_anchor,
                    page_number=section.page_number,
                    content=section.content,
                )
                for section in sections
            ],
        )
