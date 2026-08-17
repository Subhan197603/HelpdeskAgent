"""Internal corpus validation records."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CorpusValidationRun:
    run_id: UUID
    tenant_id: UUID
    run_status: str
    requested_by: UUID
    similarity_threshold: Decimal
    document_count: int
    chunk_count: int
    structural_defect_count: int
    empty_chunk_count: int
    duplicate_document_count: int
    near_duplicate_chunk_count: int
    truncated_flag: bool
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime
    row_version: int


@dataclass(frozen=True, slots=True)
class CorpusValidationFinding:
    finding_id: UUID
    finding_type: str
    document_id: UUID
    document_title: str | None
    document_version_id: UUID | None
    chunk_id: UUID | None
    counterpart_document_id: UUID | None
    counterpart_document_title: str | None
    counterpart_chunk_id: UUID | None
    duplicate_group_key: str | None
    similarity_score: Decimal | None
    suppression_flagged: bool
    evidence_json: dict[str, object]
