"""Internal corpus publication records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CorpusVersion:
    corpus_version_id: UUID
    tenant_id: UUID
    version_number: int
    validation_run_id: UUID
    published_by: UUID
    published_at: datetime
    document_count: int
    chunk_count: int
    suppressed_chunk_count: int
    active_flag: bool
    row_version: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CorpusPublicationEvent:
    publication_event_id: UUID
    action_code: str
    corpus_version_number: int
    previous_corpus_version_number: int | None
    actor_user_id: UUID
    evidence_json: dict[str, object]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationReadiness:
    validation_run_id: UUID | None
    run_completed: bool
    truncated: bool
    stale: bool
    suppression_flagged_chunks: int
