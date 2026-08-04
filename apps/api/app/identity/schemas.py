"""Public response models for the minimal identity validation API."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class AuthConfigurationResponse(BaseModel):
    """Non-secret authentication bootstrap configuration for browser clients."""

    oidc_enabled: bool
    issuer_url: str | None
    client_id: str | None
    audience: str | None
    redirect_uri: str | None
    scopes: str
    developer_identity_enabled: bool


class CurrentIdentityResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    display_name: str
    business_unit_id: UUID | None
    business_unit_name: str | None
    role_codes: list[str]
    permission_codes: list[str]
    support_group_ids: list[UUID]
    authentication_mode: Literal["developer_header", "oidc"]
    provider_code: str | None = None


class IdentityDiagnosticResponse(BaseModel):
    status: Literal["authorized"]
    authentication_mode: Literal["developer_header", "oidc"]
    provider_code: str | None
    oidc_enabled: bool
    issuer_configured: bool
    audience_configured: bool
    allowed_algorithms: list[str]
    jit_provisioning_enabled: bool
    profile_synchronization_enabled: bool
    group_synchronization_enabled: bool
    metrics: dict[str, object]
