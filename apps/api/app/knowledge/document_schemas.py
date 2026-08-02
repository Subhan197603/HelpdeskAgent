"""Contracts for document review, publication, and retirement."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentApprovalCommand(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    expected_version: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=3, max_length=2000)]


class PublishDocumentCommand(BaseModel):
    processing_version_id: UUID
    expected_document_version: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=3, max_length=2000)]


class RetireDocumentCommand(BaseModel):
    expected_version: Annotated[int, Field(ge=1)]
    reason: Annotated[str, Field(min_length=3, max_length=2000)]


class ProcessingVersionResponse(BaseModel):
    id: UUID
    document_version_id: UUID
    processing_number: int
    parser: str
    parser_version: str
    chunker: str
    chunker_version: str
    chunking_configuration_hash: str
    embedding_model_code: str
    status: str
    validation_status: str
    validation: dict[str, object]
    chunk_count: int | None
    embedded_chunk_count: int | None
    created_at: datetime
    completed_at: datetime | None


class DocumentVersionResponse(BaseModel):
    id: UUID
    version_number: int
    sha256_checksum: str
    content_type: str
    extraction_status: str
    validation_status: str
    current: bool
    published_processing_version_id: UUID | None
    acquired_at: datetime
    published_at: datetime | None
    retired_at: datetime | None
    processing_versions: list[ProcessingVersionResponse]


class DocumentAdminResponse(BaseModel):
    id: UUID
    scope: Literal["TENANT", "GLOBAL"]
    source_id: UUID
    title: str
    document_type: str
    audience_code: str
    security_classification: str
    approval_status: str
    approved_by: UUID | None
    approved_at: datetime | None
    active: bool
    row_version: int
    created_at: datetime
    updated_at: datetime
    versions: list[DocumentVersionResponse]
    replayed: bool = False
