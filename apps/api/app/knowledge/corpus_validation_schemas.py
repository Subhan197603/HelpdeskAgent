"""Contracts for persisted corpus validation runs and findings."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

CorpusFindingType = Literal[
    "STRUCTURAL_DEFECT",
    "EMPTY_CHUNK",
    "DUPLICATE_DOCUMENT",
    "NEAR_DUPLICATE_CHUNK",
]
CorpusRunStatus = Literal["COMPLETED", "FAILED"]


class CorpusValidationFindingResponse(BaseModel):
    id: UUID
    finding_type: CorpusFindingType
    document_id: UUID
    document_title: str | None
    document_version_id: UUID | None
    chunk_id: UUID | None
    counterpart_document_id: UUID | None
    counterpart_document_title: str | None
    counterpart_chunk_id: UUID | None
    duplicate_group_key: str | None
    similarity_score: float | None
    suppression_flagged: bool
    evidence: dict[str, object]


class CorpusValidationSummary(BaseModel):
    structural_defects: int = 0
    empty_chunks: int = 0
    duplicate_documents: int = 0
    near_duplicate_chunks: int = 0


class CorpusValidationReportResponse(BaseModel):
    run_id: UUID | None
    status: CorpusRunStatus | None
    requested_by: UUID | None
    similarity_threshold: float | None
    document_count: int = 0
    chunk_count: int = 0
    truncated: bool = False
    started_at: datetime | None
    completed_at: datetime | None
    summary: CorpusValidationSummary
    findings: list[CorpusValidationFindingResponse]
    replayed: bool = False
