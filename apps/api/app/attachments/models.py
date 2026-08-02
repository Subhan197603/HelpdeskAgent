"""Internal attachment lifecycle models."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Attachment:
    attachment_id: UUID
    tenant_id: UUID
    ticket_id: UUID
    ticket_key: str
    uploaded_by: UUID
    original_filename: str
    quarantine_object_uri: str
    protected_object_uri: str | None
    client_declared_content_type: str | None
    detected_mime_type: str | None
    file_size_bytes: int
    sha256_checksum: str
    malware_scan_status: str
    quarantine_status: str
    visibility_code: str
    scanner_engine: str | None
    scanner_version: str | None
    threat_name: str | None
    scan_attempt_count: int
    next_scan_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TicketScope:
    ticket_id: UUID
    tenant_id: UUID
    ticket_key: str
    reporter_user_id: UUID
    requested_for_user_id: UUID
    assignment_group_id: UUID | None
