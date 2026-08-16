"""Persistence records for acquisition administration."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    manifest_entry_id: UUID
    tenant_id: UUID | None
    source_id: UUID
    manifest_key: str
    document_title: str
    document_type: str
    audience_code: str
    canonical_url: str | None
    pdf_url: str | None
    html_url: str | None
    target_collection: str
    security_classification: str
    acquisition_permission: str
    permission_reference: str | None
    acquisition_method: str
    enabled_flag: bool
    expected_sha256: str | None
    original_filename: str | None
    declared_content_type: str | None
    declared_size_bytes: int | None
    source_last_modified_at: datetime | None
    copyright_notice: str | None
    approved_by: UUID | None
    approved_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionRun:
    ingestion_run_id: UUID
    tenant_id: UUID
    run_status: str
    requested_by: UUID
    total_items: int
    completed_items: int
    failed_items: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    row_version: int


@dataclass(frozen=True, slots=True)
class ChangeReportPage:
    ingestion_run_item_id: UUID
    manifest_key: str
    document_title: str
    item_status: str
    change_classification: str | None
    previous_sha256: str | None
    observed_sha256: str | None
    redirect_target_url: str | None
    observed_http_status: int | None
    error_code: str | None
    final_failure: bool
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class IngestionRunItem:
    ingestion_run_item_id: UUID
    manifest_entry_id: UUID
    item_status: str
    attempt_count: int
    document_id: UUID | None
    document_version_id: UUID | None
    observed_sha256: str | None
    original_filename: str | None
    declared_content_type: str | None
    detected_content_type: str | None
    file_size_bytes: int | None
    malware_scan_status: str
    error_code: str | None
    next_attempt_at: datetime
    final_failure: bool
    created_at: datetime
    updated_at: datetime
