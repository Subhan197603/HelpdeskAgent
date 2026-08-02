"""Internal knowledge-source records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class KnowledgeSource:
    source_id: UUID
    tenant_id: UUID | None
    source_code: str
    source_name: str
    source_type: str
    publisher_name: str | None
    canonical_location: str
    acquisition_method: str
    automated_access_allowed: bool
    permission_reference: str | None
    audience_scope: str
    source_status: str
    approval_status: str
    owner_user_id: UUID | None
    owner_group_id: UUID | None
    product_node_id: UUID | None
    product_code: str | None
    module_node_id: UUID | None
    module_code: str | None
    release_id: UUID | None
    release_family: str | None
    release_code: str | None
    language_code: str
    approved_by: UUID | None
    approved_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SourceAuthorization:
    authorization_id: UUID
    decision_code: str
    acquisition_method: str
    permission_reference: str
    valid_from: datetime
    valid_to: datetime | None
    decided_by: UUID
    decided_at: datetime


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    record_id: UUID
    principal_id: str
    request_hash: str
    processing_status: str
    result_resource_id: str | None
