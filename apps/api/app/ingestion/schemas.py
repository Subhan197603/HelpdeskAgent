"""Validated contracts for manifests, uploads, and acquisition runs."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

DocumentType = Literal[
    "USER_GUIDE",
    "IMPLEMENTATION_GUIDE",
    "ADMINISTRATION_GUIDE",
    "SECURITY_GUIDE",
    "API_REFERENCE",
    "TABLES_AND_VIEWS",
    "WHATS_NEW",
    "READINESS",
    "FAQ",
    "POLICY",
    "PROCEDURE",
    "RUNBOOK",
    "KNOWN_ERROR",
    "HISTORICAL_FIX",
    "ROOT_CAUSE_ANALYSIS",
    "KNOWLEDGE_ARTICLE",
    "OTHER",
]
DocumentAudience = Literal["EMPLOYEE", "ANALYST", "TECHNICAL_SPECIALIST", "ADMIN", "ALL"]
SecurityClassification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
AcquisitionMethod = Literal[
    "MANUAL_UPLOAD", "APPROVED_DIRECT_DOWNLOAD", "API_FEED", "REPOSITORY_CONNECTOR"
]
ManifestDecision = Literal["APPROVED", "REJECTED"]
Sha256 = Annotated[str, StringConstraints(to_lower=True, pattern=r"^[0-9a-f]{64}$")]
SafeFilename = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=255, pattern=r"^[^/\\\r\n]+$"
    ),
]


class ManifestEntryInput(BaseModel):
    source_id: UUID
    manifest_key: Annotated[str, Field(min_length=1, max_length=500, pattern=r"^[^\r\n]+$")]
    document_title: Annotated[str, Field(min_length=2, max_length=500)]
    document_type: DocumentType
    audience_code: DocumentAudience
    canonical_url: Annotated[str | None, Field(max_length=2000)] = None
    acquisition_url: Annotated[str, Field(min_length=8, max_length=2000)]
    target_collection: Annotated[str, Field(min_length=2, max_length=120)]
    security_classification: SecurityClassification = "INTERNAL"
    acquisition_method: Literal["APPROVED_DIRECT_DOWNLOAD", "API_FEED", "REPOSITORY_CONNECTOR"]
    expected_sha256: Sha256 | None = None
    original_filename: SafeFilename
    declared_content_type: Annotated[str, Field(min_length=3, max_length=150)]
    declared_size_bytes: Annotated[int | None, Field(gt=0)] = None
    source_last_modified_at: datetime | None = None
    copyright_notice: Annotated[str | None, Field(max_length=4000)] = None


class ManifestImportCommand(BaseModel):
    entries: Annotated[list[ManifestEntryInput], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_entries(self) -> "ManifestImportCommand":
        keys = [(entry.source_id, entry.manifest_key) for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("Manifest entries must be unique by source and key")
        return self


class ManifestApprovalCommand(BaseModel):
    decision: ManifestDecision
    permission_reference: Annotated[str, Field(min_length=3, max_length=2000)]
    expected_version: Annotated[int, Field(ge=1)]


class ManifestEntryResponse(BaseModel):
    id: UUID
    source_id: UUID
    scope: Literal["TENANT", "GLOBAL"]
    manifest_key: str
    document_title: str
    document_type: str
    audience_code: str
    acquisition_url: str | None
    acquisition_method: str
    acquisition_permission: str
    permission_reference: str | None
    enabled: bool
    expected_sha256: str | None
    original_filename: str | None
    declared_content_type: str | None
    declared_size_bytes: int | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class ManifestImportResponse(BaseModel):
    items: list[ManifestEntryResponse]
    replayed: bool = False


class AcquisitionRunCommand(BaseModel):
    manifest_entry_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_entries(self) -> "AcquisitionRunCommand":
        if len(self.manifest_entry_ids) != len(set(self.manifest_entry_ids)):
            raise ValueError("Manifest entry identifiers must be unique")
        return self


class ManualUploadCommand(BaseModel):
    source_id: UUID
    manifest_key: Annotated[str, Field(min_length=1, max_length=500, pattern=r"^[^\r\n]+$")]
    document_title: Annotated[str, Field(min_length=2, max_length=500)]
    document_type: DocumentType
    audience_code: DocumentAudience
    target_collection: Annotated[str, Field(min_length=2, max_length=120)]
    security_classification: SecurityClassification = "INTERNAL"
    filename: SafeFilename
    content_type: Annotated[str, Field(min_length=3, max_length=150)]
    file_size_bytes: Annotated[int, Field(gt=0)]
    sha256_checksum: Sha256
    copyright_notice: Annotated[str | None, Field(max_length=4000)] = None


class ManualUploadResponse(BaseModel):
    run_id: UUID
    item_id: UUID
    manifest_entry_id: UUID
    upload_url: str
    upload_headers: dict[str, str]
    quarantine_object_key: str
    expires_at: datetime
    replayed: bool = False


class UploadCompleteResponse(BaseModel):
    run_id: UUID
    item_id: UUID
    status: str
    replayed: bool = False


class RunItemResponse(BaseModel):
    id: UUID
    manifest_entry_id: UUID
    status: str
    attempt_count: int
    document_id: UUID | None
    document_version_id: UUID | None
    sha256_checksum: str | None
    filename: str | None
    declared_content_type: str | None
    detected_content_type: str | None
    file_size_bytes: int | None
    malware_scan_status: str
    error_code: str | None
    next_attempt_at: datetime
    final_failure: bool
    created_at: datetime
    updated_at: datetime


class RunResponse(BaseModel):
    id: UUID
    status: str
    requested_by: UUID
    total_items: int
    completed_items: int
    failed_items: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    row_version: int
    items: list[RunItemResponse]
    replayed: bool = False
