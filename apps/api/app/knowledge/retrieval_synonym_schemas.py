"""Contracts for the governed synonym and acronym registry."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

SynonymStatus = Literal["DRAFT", "APPROVED", "RETIRED"]


class RetrievalSynonymResponse(BaseModel):
    synonym_id: UUID
    term: str
    expansion: str
    synonym_status: SynonymStatus
    synonym_note: str | None
    decided_at: datetime
    row_version: int
    replayed: bool = False


class RetrievalSynonymCommand(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    expansion: str = Field(min_length=1, max_length=100)
    synonym_status: SynonymStatus = "DRAFT"
    synonym_note: str | None = Field(default=None, max_length=500)
    expected_row_version: int | None = Field(default=None, ge=1)


class RetrievalSynonymListResponse(BaseModel):
    items: list[RetrievalSynonymResponse]
    has_more: bool = False
