"""Stable permission codes and centralized authorization policy evaluation."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from apps.api.app.core.context import RequestContext


class Permission(StrEnum):
    SYSTEM_HEALTH_READ = "SYSTEM_HEALTH_READ"
    IDENTITY_SELF_READ = "IDENTITY_SELF_READ"
    ADMIN_IDENTITY_READ = "ADMIN_IDENTITY_READ"
    CATALOG_PROJECT_LIST = "CATALOG_PROJECT_LIST"
    CATALOG_SERVICE_READ = "CATALOG_SERVICE_READ"
    CATALOG_REQUEST_TYPE_LIST = "CATALOG_REQUEST_TYPE_LIST"
    CATALOG_FORM_READ = "CATALOG_FORM_READ"
    PROJECT_ADMIN = "PROJECT_ADMIN"
    TICKET_CREATE = "TICKET_CREATE"
    TICKET_DRAFT_CREATE = "TICKET_DRAFT_CREATE"
    TICKET_DRAFT_READ_OWN = "TICKET_DRAFT_READ_OWN"
    TICKET_DRAFT_UPDATE_OWN = "TICKET_DRAFT_UPDATE_OWN"
    TICKET_SUBMIT = "TICKET_SUBMIT"
    TICKET_REQUEST_FOR_OTHER = "TICKET_REQUEST_FOR_OTHER"
    TICKET_READ_OWN = "TICKET_READ_OWN"
    TICKET_READ_GROUP = "TICKET_READ_GROUP"
    TICKET_READ_ALL = "TICKET_READ_ALL"
    TICKET_ANALYST_READ = "TICKET_ANALYST_READ"
    TICKET_COMMENT_PUBLIC = "TICKET_COMMENT_PUBLIC"
    TICKET_UPDATE_GROUP = "TICKET_UPDATE_GROUP"
    TICKET_TRANSITION = "TICKET_TRANSITION"
    KNOWLEDGE_READ_EMPLOYEE = "KNOWLEDGE_READ_EMPLOYEE"
    KNOWLEDGE_READ_ANALYST = "KNOWLEDGE_READ_ANALYST"
    AI_EMPLOYEE_USE = "AI_EMPLOYEE_USE"
    AI_ANALYST_USE = "AI_ANALYST_USE"


INITIAL_ROLE_CODES = frozenset(
    {
        "PLATFORM_ADMIN",
        "PROJECT_ADMIN",
        "SERVICE_OWNER",
        "SUPPORT_MANAGER",
        "AGENT",
        "CUSTOMER",
        "APPROVER",
        "KNOWLEDGE_AUTHOR",
        "KNOWLEDGE_APPROVER",
        "AUDITOR",
        "AI_ADMIN",
        "REPORTING_USER",
    }
)

CATALOGUE_READ_PERMISSIONS = frozenset(
    {
        Permission.CATALOG_PROJECT_LIST,
        Permission.CATALOG_SERVICE_READ,
        Permission.CATALOG_REQUEST_TYPE_LIST,
        Permission.CATALOG_FORM_READ,
    }
)

# Self-read is an authenticated-caller permission and does not depend on a role assignment.
# Catalogue access requires at least one recognized employee role; roleless JIT users remain
# privilege-free until an administrator assigns an application role.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    role_code: CATALOGUE_READ_PERMISSIONS
    | frozenset(
        {
            Permission.TICKET_DRAFT_CREATE,
            Permission.TICKET_DRAFT_READ_OWN,
            Permission.TICKET_DRAFT_UPDATE_OWN,
            Permission.TICKET_SUBMIT,
            Permission.TICKET_READ_OWN,
        }
    )
    for role_code in INITIAL_ROLE_CODES
}
ROLE_PERMISSIONS["PLATFORM_ADMIN"] = CATALOGUE_READ_PERMISSIONS | frozenset(
    {
        Permission.ADMIN_IDENTITY_READ,
        Permission.TICKET_DRAFT_CREATE,
        Permission.TICKET_DRAFT_READ_OWN,
        Permission.TICKET_DRAFT_UPDATE_OWN,
        Permission.TICKET_SUBMIT,
        Permission.TICKET_READ_OWN,
        Permission.TICKET_READ_ALL,
        Permission.TICKET_ANALYST_READ,
        Permission.TICKET_COMMENT_PUBLIC,
        Permission.TICKET_TRANSITION,
        Permission.TICKET_REQUEST_FOR_OTHER,
    }
)
ROLE_PERMISSIONS["PROJECT_ADMIN"] |= frozenset(
    {
        Permission.TICKET_READ_ALL,
        Permission.TICKET_ANALYST_READ,
        Permission.TICKET_COMMENT_PUBLIC,
        Permission.TICKET_TRANSITION,
    }
)
for analyst_role in ("AGENT", "SUPPORT_MANAGER"):
    ROLE_PERMISSIONS[analyst_role] |= frozenset(
        {
            Permission.TICKET_READ_GROUP,
            Permission.TICKET_ANALYST_READ,
            Permission.TICKET_COMMENT_PUBLIC,
            Permission.TICKET_TRANSITION,
        }
    )
ROLE_PERMISSIONS["CUSTOMER"] |= frozenset({Permission.TICKET_COMMENT_PUBLIC})


@dataclass(frozen=True, slots=True)
class AuthorizationResource:
    """Future-safe policy dimensions; unset dimensions do not imply authorization."""

    tenant_id: UUID | None = None
    service_project_id: UUID | None = None
    owner_user_id: UUID | None = None
    reporter_user_id: UUID | None = None
    requested_for_user_id: UUID | None = None
    participant_user_ids: frozenset[UUID] = frozenset()
    support_group_id: UUID | None = None
    business_unit_id: UUID | None = None
    security_classification: str | None = None
    environment_code: str | None = None
    tool_code: str | None = None


class AuthorizationService:
    """Evaluate stable permissions without placing role checks in route handlers."""

    def permissions_for(self, context: RequestContext) -> frozenset[Permission]:
        if not context.is_authenticated:
            return frozenset()
        permissions = {Permission.IDENTITY_SELF_READ}
        for role_code in context.roles:
            permissions.update(ROLE_PERMISSIONS.get(role_code, frozenset()))
        return frozenset(permissions)

    def is_allowed(
        self,
        context: RequestContext,
        permission: Permission,
        resource: AuthorizationResource | None = None,
    ) -> bool:
        if not context.is_authenticated:
            return False
        if resource is not None and resource.tenant_id not in {None, context.tenant_id}:
            return False
        return permission in self.permissions_for(context)
