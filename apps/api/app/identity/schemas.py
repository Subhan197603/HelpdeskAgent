"""Public response models for the minimal identity validation API."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class CurrentIdentityResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    display_name: str
    business_unit_id: UUID | None
    business_unit_name: str | None
    role_codes: list[str]
    support_group_ids: list[UUID]
    authentication_mode: Literal["developer_header"]


class IdentityDiagnosticResponse(BaseModel):
    status: Literal["authorized"]
    authentication_mode: Literal["developer_header"]
