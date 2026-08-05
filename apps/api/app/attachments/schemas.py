"""Attachment API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(min_length=1, max_length=200)
    file_size_bytes: int = Field(ge=1)
    sha256_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    visibility: Literal["PUBLIC", "INTERNAL"] = "PUBLIC"

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("filename must be a base filename")
        return normalized

    @field_validator("content_type")
    @classmethod
    def normalized_content_type(cls, value: str) -> str:
        return value.split(";", 1)[0].strip().lower()


class UploadAuthorizationResponse(BaseModel):
    attachment_id: UUID
    upload_url: str
    upload_headers: dict[str, str]
    expires_at: datetime


class FinalizeResponse(BaseModel):
    attachment_id: UUID
    ticket_key: str
    filename: str
    content_type: str
    file_size_bytes: int
    sha256_checksum: str
    scan_status: Literal["CLEAN", "INFECTED", "ERROR"]
    quarantine_status: Literal["RELEASED", "REJECTED", "QUARANTINED"]
    scanner_engine: str | None
    scanner_version: str | None
    created_at: datetime


class DownloadResponse(BaseModel):
    attachment_id: UUID
    download_url: str
    expires_at: datetime


class AttachmentSummaryResponse(BaseModel):
    """Metadata only — downloads always go through the presign endpoint."""

    id: UUID
    filename: str
    content_type: str
    size_bytes: int
    scan_status: str
    visibility: str
    uploaded_by_name: str | None
    created_at: datetime


class AttachmentListResponse(BaseModel):
    ticket_key: str
    items: list[AttachmentSummaryResponse]
