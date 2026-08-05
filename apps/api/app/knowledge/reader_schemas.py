"""Published knowledge article reading contracts."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ReaderPersona = Literal["EMPLOYEE", "ANALYST"]
DocumentTypeCode = Literal[
    "USER_GUIDE",
    "IMPLEMENTATION_GUIDE",
    "ADMINISTRATION_GUIDE",
    "SECURITY_GUIDE",
    "API_REFERENCE",
    "TABLES_AND_VIEWS",
    "WHATS_NEW",
    "READINESS",
    "FAQ",
    "POLICY",
    "PROCEDURE",
    "RUNBOOK",
    "KNOWN_ERROR",
    "HISTORICAL_FIX",
    "ROOT_CAUSE_ANALYSIS",
    "KNOWLEDGE_ARTICLE",
    "OTHER",
]


class KnowledgeArticleSummary(BaseModel):
    id: UUID
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


class KnowledgeArticleFacet(BaseModel):
    document_type: str
    count: int


class KnowledgeArticleListResponse(BaseModel):
    items: list[KnowledgeArticleSummary]
    facets: list[KnowledgeArticleFacet]
    has_more: bool


class KnowledgeArticleSection(BaseModel):
    heading_path: str | None
    section_title: str | None
    section_anchor: str | None
    page_number: int | None
    content: str


class KnowledgeArticleDetailResponse(BaseModel):
    id: UUID
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
    sections: list[KnowledgeArticleSection] = Field(default_factory=list)
