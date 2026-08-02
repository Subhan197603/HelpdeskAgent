"""Administrative document publication records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    document_id: UUID
    tenant_id: UUID | None
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


@dataclass(frozen=True, slots=True)
class ProcessingRecord:
    processing_version_id: UUID
    document_version_id: UUID
    processing_number: int
    parser_name: str
    parser_version: str
    chunker_name: str
    chunker_version: str
    chunking_configuration_hash: str
    embedding_model_code: str
    processing_status: str
    validation_status: str
    validation_json: dict[str, object]
    chunk_count: int | None
    embedded_chunk_count: int | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class VersionRecord:
    document_version_id: UUID
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
