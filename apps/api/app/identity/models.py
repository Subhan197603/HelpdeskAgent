"""Identity application models that are independent of persistence and transport."""

from dataclasses import dataclass
from uuid import UUID

from apps.api.app.core.context import RequestContext


@dataclass(frozen=True, slots=True)
class TenantIdentity:
    tenant_id: UUID
    tenant_code: str
    active: bool


@dataclass(frozen=True, slots=True)
class UserIdentity:
    user_id: UUID
    tenant_id: UUID
    external_subject: str
    display_name: str
    business_unit_id: UUID | None
    active: bool


@dataclass(frozen=True, slots=True)
class BusinessUnitIdentity:
    business_unit_id: UUID
    business_unit_name: str


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    context: RequestContext
    display_name: str
    business_unit_name: str | None
    authentication_mode: str = "developer_header"
