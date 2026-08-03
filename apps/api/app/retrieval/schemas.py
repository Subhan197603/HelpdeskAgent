"""Public, bounded evidence-search contracts without internal ranking configuration."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints

Code = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class EvidenceFilters(BaseModel):
    product_codes: Annotated[list[Code], Field(max_length=20)] = Field(default_factory=list)
    module_codes: Annotated[list[Code], Field(max_length=20)] = Field(default_factory=list)
    release_families: Annotated[list[Code], Field(max_length=20)] = Field(default_factory=list)
    release_codes: Annotated[list[Code], Field(max_length=20)] = Field(default_factory=list)
    language_codes: Annotated[list[Code], Field(max_length=20)] = Field(default_factory=list)
    source_ids: Annotated[list[UUID], Field(max_length=20)] = Field(default_factory=list)


class EvidenceSearchRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    persona: Literal["EMPLOYEE", "ANALYST"] = "EMPLOYEE"
    filters: EvidenceFilters = Field(default_factory=EvidenceFilters)
    limit: Annotated[int, Field(ge=1, le=50)] = 8


class EvidenceScoreComponents(BaseModel):
    lexical: float | None
    vector: float | None
    fusion: float
    exact_identifier_boost: float
    metadata_boost: float
    source_authority_boost: float
    rerank: float | None


class EvidenceItem(BaseModel):
    rank: int
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_id: UUID
    document_title: str
    document_type: str | None
    heading_path: str | None
    section_title: str | None
    section_anchor: str | None
    content: str
    language_code: str
    release_family: str | None
    release_code: str | None
    product_code: str | None
    product_name: str | None
    module_code: str | None
    module_name: str | None
    source_type: str
    canonical_uri: str
    page_number: int | None
    final_score: float
    score_components: EvidenceScoreComponents


class EvidenceSearchResponse(BaseModel):
    normalized_query: str
    retrieval_configuration_version_id: UUID
    evidence: list[EvidenceItem]
