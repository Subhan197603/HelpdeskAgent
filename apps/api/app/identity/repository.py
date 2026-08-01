"""Narrow PostgreSQL queries for developer identity resolution."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.identity.models import BusinessUnitIdentity, TenantIdentity, UserIdentity

_TENANT_BY_CODE = text(
    """
    SELECT tenant_id, tenant_code, active_flag
    FROM identity.tenant
    WHERE tenant_code = :tenant_code
    """
)
_USER_BY_SUBJECT = text(
    """
    SELECT user_id, tenant_id, external_subject, display_name, business_unit_id, active_flag
    FROM identity.app_user
    WHERE tenant_id = :tenant_id AND external_subject = :external_subject
    """
)
_EFFECTIVE_ROLES = text(
    """
    SELECT DISTINCT ur.role_code
    FROM identity.user_role AS ur
    JOIN identity.role_definition AS rd ON rd.role_code = ur.role_code
    WHERE ur.tenant_id = :tenant_id
      AND ur.user_id = :user_id
      AND ur.active_flag
      AND rd.active_flag
      AND ur.valid_from <= CURRENT_TIMESTAMP
      AND (ur.valid_to IS NULL OR ur.valid_to > CURRENT_TIMESTAMP)
    """
)
_EFFECTIVE_SUPPORT_GROUPS = text(
    """
    SELECT DISTINCT sg.support_group_id
    FROM identity.support_group_member AS member
    JOIN identity.support_group AS sg
      ON sg.support_group_id = member.support_group_id
     AND sg.tenant_id = :tenant_id
    WHERE member.user_id = :user_id
      AND member.active_flag
      AND sg.active_flag
    """
)
_BUSINESS_UNIT = text(
    """
    SELECT business_unit_id, business_unit_name
    FROM identity.business_unit
    WHERE business_unit_id = :business_unit_id
      AND tenant_id = :tenant_id
      AND active_flag
    """
)


class IdentityRepository:
    """Read only the identity records needed to establish one caller context."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def tenant_by_code(self, tenant_code: str) -> TenantIdentity | None:
        row = (
            await self._session.execute(_TENANT_BY_CODE, {"tenant_code": tenant_code})
        ).one_or_none()
        if row is None:
            return None
        return TenantIdentity(row.tenant_id, row.tenant_code, row.active_flag)

    async def user_by_external_subject(
        self, tenant_id: UUID, external_subject: str
    ) -> UserIdentity | None:
        row = (
            await self._session.execute(
                _USER_BY_SUBJECT,
                {"tenant_id": tenant_id, "external_subject": external_subject},
            )
        ).one_or_none()
        if row is None:
            return None
        return UserIdentity(
            row.user_id,
            row.tenant_id,
            row.external_subject,
            row.display_name,
            row.business_unit_id,
            row.active_flag,
        )

    async def effective_roles(self, tenant_id: UUID, user_id: UUID) -> frozenset[str]:
        rows = await self._session.execute(
            _EFFECTIVE_ROLES, {"tenant_id": tenant_id, "user_id": user_id}
        )
        return frozenset(str(row.role_code) for row in rows)

    async def effective_support_group_ids(self, tenant_id: UUID, user_id: UUID) -> frozenset[UUID]:
        rows = await self._session.execute(
            _EFFECTIVE_SUPPORT_GROUPS, {"tenant_id": tenant_id, "user_id": user_id}
        )
        return frozenset(row.support_group_id for row in rows)

    async def active_business_unit(
        self, tenant_id: UUID, business_unit_id: UUID | None
    ) -> BusinessUnitIdentity | None:
        if business_unit_id is None:
            return None
        row = (
            await self._session.execute(
                _BUSINESS_UNIT,
                {"tenant_id": tenant_id, "business_unit_id": business_unit_id},
            )
        ).one_or_none()
        if row is None:
            return None
        return BusinessUnitIdentity(row.business_unit_id, row.business_unit_name)
