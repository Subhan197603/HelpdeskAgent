"""Knowledge-source administration contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, StringConstraints, model_validator

SourceType = Literal[
    "ORACLE_PUBLIC_DOCUMENTATION",
    "COMPANY_POLICY",
    "COMPANY_PROCEDURE",
    "INTERNAL_KNOWLEDGE",
    "HISTORICAL_RESOLUTION",
    "OTHER_EXTERNAL",
]
AcquisitionMethod = Literal[
    "MANUAL_UPLOAD",
    "APPROVED_DIRECT_DOWNLOAD",
    "API_FEED",
    "REPOSITORY_CONNECTOR",
    "TICKET_PUBLICATION",
]
AudienceScope = Literal["EMPLOYEE", "ANALYST", "RESTRICTED", "ADMINISTRATIVE"]
SourceStatus = Literal["ACTIVE", "DISABLED", "RETIRED"]
ApprovalStatus = Literal["DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED"]
SourceScope = Literal["TENANT", "GLOBAL"]
RefreshState = Literal["CURRENT", "REFRESH_DUE", "REFRESHING", "STALE"]
EffectiveRefreshState = Literal["CURRENT", "REFRESH_DUE", "REFRESHING", "STALE", "RETIRED"]
RefreshLifecycleAction = Literal["MARK_REFRESH_DUE", "MARK_CURRENT", "MARK_STALE"]
SourceCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_upper=True,
        min_length=2,
        max_length=80,
        pattern=r"^[A-Z][A-Z0-9_]*$",
    ),
]


class SourceDefinition(BaseModel):
    code: SourceCode
    name: Annotated[str, Field(min_length=2, max_length=250)]
    source_type: SourceType
    publisher_name: Annotated[str | None, Field(max_length=200)] = None
    canonical_location: Annotated[str, Field(min_length=3, max_length=2000)]
    acquisition_method: AcquisitionMethod
    permission_reference: Annotated[str | None, Field(max_length=2000)] = None
    audience_scope: AudienceScope
    status: SourceStatus = "ACTIVE"
    owner_user_id: UUID | None = None
    owner_group_id: UUID | None = None
    product_node_id: UUID | None = None
    module_node_id: UUID | None = None
    release_id: UUID | None = None
    language_code: Annotated[
        str, Field(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$", min_length=2, max_length=20)
    ] = "en"

    @model_validator(mode="after")
    def require_owner(self) -> "SourceDefinition":
        if self.owner_user_id is None and self.owner_group_id is None:
            raise ValueError("A source owner user or group is required")
        if self.product_node_id == self.module_node_id and self.product_node_id is not None:
            raise ValueError("Product and module nodes must be different")
        return self


class SourceCreate(SourceDefinition):
    scope: SourceScope = "TENANT"


class SourceUpdate(SourceDefinition):
    expected_version: Annotated[int, Field(ge=1)]


class SourceApprovalCommand(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    expected_version: Annotated[int, Field(ge=1)]


class RefreshLifecycleCommand(BaseModel):
    action: RefreshLifecycleAction
    expected_version: Annotated[int, Field(ge=1)]
    refresh_due_at: datetime | None = None

    @model_validator(mode="after")
    def validate_due_date(self) -> "RefreshLifecycleCommand":
        if self.refresh_due_at is not None and self.action != "MARK_REFRESH_DUE":
            raise ValueError("refresh_due_at is only accepted with MARK_REFRESH_DUE")
        return self


class AcquisitionAuthorizationCommand(BaseModel):
    decision: Literal["APPROVED", "REVOKED"]
    acquisition_method: Literal["APPROVED_DIRECT_DOWNLOAD", "API_FEED", "REPOSITORY_CONNECTOR"]
    permission_reference: Annotated[str, Field(min_length=3, max_length=2000)]
    expected_version: Annotated[int, Field(ge=1)]
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "AcquisitionAuthorizationCommand":
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class SourceResponse(BaseModel):
    id: UUID
    scope: SourceScope
    code: str
    name: str
    source_type: SourceType
    publisher_name: str | None
    canonical_location: str
    acquisition_method: AcquisitionMethod
    automated_access_allowed: bool
    permission_reference: str | None
    audience_scope: AudienceScope
    status: SourceStatus
    approval_status: ApprovalStatus
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
    refresh_state: RefreshState
    effective_refresh_state: EffectiveRefreshState
    refresh_due_at: datetime | None
    last_refresh_requested_at: datetime | None
    last_refresh_requested_by: UUID | None
    last_refresh_completed_at: datetime | None
    last_acquisition_status: str | None
    last_acquisition_at: datetime | None


class SourceList(BaseModel):
    items: list[SourceResponse]
    total: int = 0
    offset: int = 0
    has_more: bool = False


class AcquisitionAuthorizationResponse(BaseModel):
    id: UUID
    decision: Literal["APPROVED", "REVOKED"]
    acquisition_method: str
    permission_reference: str
    valid_from: datetime
    valid_to: datetime | None
    decided_by: UUID
    decided_at: datetime
    source: SourceResponse
    replayed: bool = False


class AcquisitionPermissionResponse(BaseModel):
    source_id: UUID
    allowed: bool
    reasons: list[str]
    evaluated_at: datetime
