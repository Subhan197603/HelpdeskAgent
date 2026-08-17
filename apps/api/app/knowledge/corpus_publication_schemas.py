"""Contracts for governed corpus publication and rollback."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

CorpusPublicationAction = Literal["PUBLISHED", "ROLLED_BACK"]


class CorpusVersionResponse(BaseModel):
    id: UUID
    version_number: int
    validation_run_id: UUID
    published_by: UUID
    published_at: datetime
    document_count: int
    chunk_count: int
    suppressed_chunk_count: int
    active: bool
    replayed: bool = False


class CorpusPublicationReadinessResponse(BaseModel):
    publishable: bool
    blockers: list[str]
    validation_run_id: UUID | None
    suppression_flagged_chunks: int = 0


class ActiveCorpusVersionResponse(BaseModel):
    active_version: CorpusVersionResponse | None
    readiness: CorpusPublicationReadinessResponse


class CorpusPublicationEventResponse(BaseModel):
    id: UUID
    action: CorpusPublicationAction
    corpus_version_number: int
    previous_corpus_version_number: int | None
    actor_user_id: UUID
    evidence: dict[str, object]
    occurred_at: datetime


class CorpusVersionHistoryResponse(BaseModel):
    versions: list[CorpusVersionResponse]
    events: list[CorpusPublicationEventResponse]
