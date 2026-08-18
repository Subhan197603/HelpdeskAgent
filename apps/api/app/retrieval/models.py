"""Deterministic internal contracts for authorized retrieval and evidence."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID


class CandidateKind(StrEnum):
    LEXICAL = "LEXICAL"
    VECTOR = "VECTOR"
    ERROR_CODE = "ERROR_CODE"


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    product_codes: tuple[str, ...] = ()
    module_codes: tuple[str, ...] = ()
    release_families: tuple[str, ...] = ()
    release_codes: tuple[str, ...] = ()
    language_codes: tuple[str, ...] = ()
    source_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    query: str
    query_embedding: tuple[float, ...]
    filters: RetrievalFilters = RetrievalFilters()
    limit: int = 12
    persona: str = "EMPLOYEE"
    embedding_model_code: str = "DEFAULT_1536"


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    rank: int
    kind: CandidateKind
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_id: UUID
    document_title: str
    heading_path: str | None
    content_text: str
    language_code: str
    release_family: str | None
    release_code: str | None
    product_code: str | None
    product_name: str | None
    module_code: str | None
    module_name: str | None
    source_type: str
    canonical_uri: str
    section_title: str | None
    section_anchor: str | None
    page_number: int | None
    score: float
    document_type: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalCandidates:
    normalized_query: str
    embedding_model_code: str
    lexical: tuple[RetrievalCandidate, ...]
    vector: tuple[RetrievalCandidate, ...]


@dataclass(frozen=True, slots=True)
class RetrievalConfiguration:
    version_id: UUID
    rrf_k: int
    lexical_weight: float
    vector_weight: float
    exact_identifier_boost: float
    metadata_boost: float
    rerank_weight: float
    reranking_enabled: bool
    source_authority_weights: Mapping[str, float] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class ScoreComponents:
    lexical: float | None
    vector: float | None
    fusion: float
    exact_identifier_boost: float
    metadata_boost: float
    source_authority_boost: float
    rerank: float | None


@dataclass(frozen=True, slots=True)
class RetrievalEvidence:
    rank: int
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_id: UUID
    document_title: str
    heading_path: str | None
    section_title: str | None
    section_anchor: str | None
    content_text: str
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
    score: float
    components: ScoreComponents
    document_type: str | None = None


@dataclass(frozen=True, slots=True)
class RetrievalEvidenceSet:
    normalized_query: str
    retrieval_configuration_version_id: UUID
    evidence: tuple[RetrievalEvidence, ...]
