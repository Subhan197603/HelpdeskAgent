"""Published-article reads that reuse the hard SQL eligibility rules of retrieval."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.retrieval.repository import RetrievalPrincipal

_ELIGIBLE_DOCUMENTS = """
WITH eligible_documents AS (
  SELECT d.document_id,d.document_title,d.document_type,d.audience_code,
    d.security_classification,d.language_code,d.canonical_url,
    d.policy_owner,d.process_owner,d.owner_group_id,d.updated_at,d.next_review_date,
    s.source_type,s.source_name,r.release_code,pn.product_name,
    dv.document_version_id,dv.version_number,dv.published_at,
    dv.published_processing_version_id
  FROM kb.document d
  JOIN kb.document_version dv ON dv.document_id=d.document_id
    AND dv.current_version_flag AND dv.validation_status IN ('PASSED','WARNING')
    AND dv.published_processing_version_id IS NOT NULL
  JOIN kb.source s ON s.source_id=d.source_id AND s.active_flag
    AND s.source_status='ACTIVE' AND s.approval_status='APPROVED'
  LEFT JOIN kb.release r ON r.release_id=d.release_id
  LEFT JOIN kb.product_node pn ON pn.product_node_id=d.product_node_id
  WHERE (d.tenant_id IS NULL OR d.tenant_id=:tenant_id)
    AND d.active_flag AND d.approval_status='APPROVED'
    AND (d.effective_from IS NULL OR d.effective_from<=CURRENT_DATE)
    AND (d.effective_to IS NULL OR d.effective_to>=CURRENT_DATE)
    AND (d.next_review_date IS NULL OR d.next_review_date>=CURRENT_DATE)
    AND d.audience_code=ANY(CAST(:audiences AS text[]))
    AND d.security_classification=ANY(CAST(:security_levels AS text[]))
    AND (
      NOT EXISTS (
        SELECT 1 FROM kb.document_permission permission
        WHERE permission.document_id=d.document_id
      )
      OR EXISTS (
        SELECT 1 FROM kb.document_permission permission
        WHERE permission.document_id=d.document_id
          AND permission.permission_code IN ('READ','AUTHOR','APPROVE','ADMINISTER')
          AND (
            (permission.principal_type='USER'
              AND permission.principal_code=CAST(:user_id AS text))
            OR (permission.principal_type='ROLE'
              AND permission.principal_code=ANY(CAST(:roles AS text[])))
            OR (permission.principal_type='SUPPORT_GROUP'
              AND (
                permission.principal_code=ANY(CAST(:support_groups AS text[]))
                OR EXISTS (
                  SELECT 1 FROM identity.support_group support_group
                  WHERE support_group.tenant_id=:tenant_id
                    AND support_group.support_group_id=ANY(
                      CAST(:support_groups AS uuid[]))
                    AND support_group.group_code=permission.principal_code)))
            OR (permission.principal_type='BUSINESS_UNIT'
              AND CAST(:business_unit AS text) IS NOT NULL
              AND (
                permission.principal_code=CAST(:business_unit AS text)
                OR EXISTS (
                  SELECT 1 FROM identity.business_unit business_unit
                  WHERE business_unit.tenant_id=:tenant_id
                    AND business_unit.business_unit_id=CAST(:business_unit AS uuid)
                    AND business_unit.business_unit_code=permission.principal_code)))
            OR (permission.principal_type='ALL_EMPLOYEES')
            OR (permission.principal_type='ALL_ANALYSTS' AND :persona='ANALYST')
          )
      )
    )
)
"""

_ARTICLES = text(
    _ELIGIBLE_DOCUMENTS
    + """
SELECT eligible.document_id,eligible.document_title,eligible.document_type,
  eligible.source_type,eligible.source_name,left(excerpt.content_text,280) AS excerpt,
  eligible.language_code,eligible.product_name,eligible.release_code,
  eligible.audience_code,eligible.published_at,eligible.updated_at
FROM eligible_documents eligible
LEFT JOIN LATERAL (
  SELECT chunk.content_text
  FROM kb.document_chunk chunk
  WHERE chunk.document_version_id=eligible.document_version_id
    AND chunk.processing_version_id=eligible.published_processing_version_id
    AND chunk.tenant_id=:tenant_id
  ORDER BY chunk.chunk_sequence
  LIMIT 1
) excerpt ON TRUE
WHERE (CAST(:document_type AS text) IS NULL OR eligible.document_type=:document_type)
ORDER BY GREATEST(eligible.updated_at,COALESCE(eligible.published_at,eligible.updated_at)) DESC,
  eligible.document_id
LIMIT :result_limit OFFSET :result_offset
"""
)

_FACETS = text(
    _ELIGIBLE_DOCUMENTS
    + """
SELECT eligible.document_type,COUNT(*) AS article_count
FROM eligible_documents eligible
GROUP BY eligible.document_type
ORDER BY article_count DESC,eligible.document_type
"""
)

_ARTICLE = text(
    _ELIGIBLE_DOCUMENTS
    + """
SELECT eligible.*,owner_group.group_name AS owner_group_name
FROM eligible_documents eligible
LEFT JOIN identity.support_group owner_group
  ON owner_group.support_group_id=eligible.owner_group_id
  AND owner_group.tenant_id=:tenant_id
WHERE eligible.document_id=:document_id
"""
)

_SECTIONS = text("""
SELECT chunk.heading_path,chunk.section_title,chunk.section_anchor,
  chunk.page_number,chunk.content_text
FROM kb.document_chunk chunk
WHERE chunk.document_version_id=:document_version_id
  AND chunk.processing_version_id=:processing_version_id
  AND chunk.tenant_id=:tenant_id
ORDER BY chunk.chunk_sequence
""")


@dataclass(frozen=True, slots=True)
class ArticleSummaryRow:
    document_id: UUID
    title: str
    document_type: str
    source_type: str
    source_name: str
    excerpt: str | None
    language_code: str
    product_name: str | None
    release_code: str | None
    audience_code: str
    published_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ArticleFacetRow:
    document_type: str
    count: int


@dataclass(frozen=True, slots=True)
class ArticleDetailRow:
    document_id: UUID
    title: str
    document_type: str
    source_type: str
    source_name: str
    audience_code: str
    security_classification: str
    language_code: str
    product_name: str | None
    release_code: str | None
    canonical_url: str | None
    owner_group_name: str | None
    policy_owner: str | None
    process_owner: str | None
    version_number: int
    published_at: datetime | None
    updated_at: datetime
    next_review_date: date | None
    document_version_id: UUID
    published_processing_version_id: UUID


@dataclass(frozen=True, slots=True)
class ArticleSectionRow:
    heading_path: str | None
    section_title: str | None
    section_anchor: str | None
    page_number: int | None
    content: str


def _principal_parameters(principal: RetrievalPrincipal) -> dict[str, object]:
    return {
        "tenant_id": principal.tenant_id,
        "user_id": principal.user_id,
        "roles": list(principal.role_codes),
        "support_groups": list(principal.support_group_codes),
        "business_unit": principal.business_unit_code,
        "audiences": list(principal.audience_codes),
        "security_levels": list(principal.security_levels),
        "persona": principal.persona,
    }


class KnowledgeReaderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def articles(
        self,
        principal: RetrievalPrincipal,
        document_type: str | None,
        limit: int,
        offset: int,
    ) -> tuple[ArticleSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _ARTICLES,
                {
                    **_principal_parameters(principal),
                    "document_type": document_type,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            ArticleSummaryRow(
                document_id=row.document_id,
                title=row.document_title,
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
            for row in rows
        )

    async def facets(self, principal: RetrievalPrincipal) -> tuple[ArticleFacetRow, ...]:
        rows = (await self._session.execute(_FACETS, _principal_parameters(principal))).all()
        return tuple(
            ArticleFacetRow(document_type=row.document_type, count=int(row.article_count))
            for row in rows
        )

    async def article(
        self, principal: RetrievalPrincipal, document_id: UUID
    ) -> ArticleDetailRow | None:
        row = (
            await self._session.execute(
                _ARTICLE,
                {**_principal_parameters(principal), "document_id": document_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return ArticleDetailRow(
            document_id=row.document_id,
            title=row.document_title,
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
            document_version_id=row.document_version_id,
            published_processing_version_id=row.published_processing_version_id,
        )

    async def sections(
        self,
        tenant_id: UUID,
        document_version_id: UUID,
        processing_version_id: UUID,
    ) -> tuple[ArticleSectionRow, ...]:
        rows = (
            await self._session.execute(
                _SECTIONS,
                {
                    "tenant_id": tenant_id,
                    "document_version_id": document_version_id,
                    "processing_version_id": processing_version_id,
                },
            )
        ).all()
        return tuple(
            ArticleSectionRow(
                heading_path=row.heading_path,
                section_title=row.section_title,
                section_anchor=row.section_anchor,
                page_number=row.page_number,
                content=row.content_text,
            )
            for row in rows
        )
