"""Deterministic internal contracts for independent retrieval candidate lists."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class CandidateKind(StrEnum):
    LEXICAL = "LEXICAL"
    VECTOR = "VECTOR"


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
    source_type: str
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalCandidates:
    normalized_query: str
    embedding_model_code: str
    lexical: tuple[RetrievalCandidate, ...]
    vector: tuple[RetrievalCandidate, ...]
