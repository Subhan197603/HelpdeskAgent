"""Narrow PostgreSQL queries for local and OIDC identity resolution."""

import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.identity.models import (
    BusinessUnitIdentity,
    ExternalUserIdentity,
    OidcTenantMapping,
    TenantIdentity,
    UserIdentity,
)

_TENANT_BY_CODE = text(
    """
    SELECT tenant_id, tenant_code, active_flag
    FROM identity.tenant
    WHERE tenant_code = :tenant_code
    """
)
_USER_BY_SUBJECT = text(
    """
    SELECT user_id, tenant_id, external_subject, display_name, email_address, locale_code,
           business_unit_id, active_flag
    FROM identity.app_user
    WHERE tenant_id = :tenant_id AND external_subject = :external_subject
    """
)
_OIDC_TENANT_MAPPING = text(
    """
    SELECT mapping.oidc_tenant_mapping_id, mapping.tenant_id,
           mapping.active_flag AS mapping_active, tenant.active_flag AS tenant_active
    FROM identity.oidc_tenant_mapping AS mapping
    JOIN identity.tenant AS tenant ON tenant.tenant_id = mapping.tenant_id
    WHERE mapping.provider_code = :provider_code
      AND mapping.trusted_issuer = :trusted_issuer
      AND mapping.organization_claim_value IS NOT DISTINCT FROM :organization_claim_value
    """
)
_EXTERNAL_IDENTITY = text(
    """
    SELECT external.external_identity_id,
           external.active_flag AS external_identity_active,
           app_user.user_id, app_user.tenant_id, app_user.external_subject,
           app_user.display_name, app_user.email_address, app_user.locale_code,
           app_user.business_unit_id, app_user.active_flag
    FROM identity.external_identity AS external
    JOIN identity.app_user AS app_user
      ON app_user.tenant_id = external.tenant_id AND app_user.user_id = external.user_id
    WHERE external.tenant_id = :tenant_id
      AND external.oidc_tenant_mapping_id = :mapping_id
      AND external.external_subject = :external_subject
    """
)
_CREATE_JIT_USER = text(
    """
    INSERT INTO identity.app_user (
        tenant_id, external_subject, email_address, display_name, locale_code
    ) VALUES (
        :tenant_id, :external_subject, :email_address, :display_name, :locale_code
    )
    RETURNING user_id, tenant_id, external_subject, display_name, email_address, locale_code,
              business_unit_id, active_flag
    """
)
_CREATE_EXTERNAL_IDENTITY = text(
    """
    INSERT INTO identity.external_identity (
        tenant_id, oidc_tenant_mapping_id, user_id, external_subject,
        last_authenticated_at, last_synchronized_at, safe_provider_metadata_json
    ) VALUES (
        :tenant_id, :mapping_id, :user_id, :external_subject,
        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CAST(:safe_metadata AS jsonb)
    )
    RETURNING external_identity_id
    """
)
_SYNC_PROFILE = text(
    """
    UPDATE identity.app_user
    SET display_name = COALESCE(:display_name, display_name),
        email_address = COALESCE(:email_address, email_address),
        locale_code = COALESCE(:locale_code, locale_code)
    WHERE tenant_id = :tenant_id AND user_id = :user_id
      AND (
        display_name IS DISTINCT FROM COALESCE(:display_name, display_name)
        OR email_address IS DISTINCT FROM COALESCE(:email_address, email_address)
        OR locale_code IS DISTINCT FROM COALESCE(:locale_code, locale_code)
      )
    RETURNING user_id
    """
)
_TOUCH_EXTERNAL_IDENTITY = text(
    """
    UPDATE identity.external_identity
    SET last_authenticated_at = CURRENT_TIMESTAMP,
        last_synchronized_at = CASE
            WHEN :synchronized THEN CURRENT_TIMESTAMP ELSE last_synchronized_at
        END,
        safe_provider_metadata_json = CAST(:safe_metadata AS jsonb)
    WHERE external_identity_id = :external_identity_id
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
            row.email_address,
            row.locale_code,
            row.business_unit_id,
            row.active_flag,
        )

    async def oidc_tenant_mapping(
        self,
        provider_code: str,
        trusted_issuer: str,
        organization_claim_value: str | None,
    ) -> OidcTenantMapping | None:
        row = (
            await self._session.execute(
                _OIDC_TENANT_MAPPING,
                {
                    "provider_code": provider_code,
                    "trusted_issuer": trusted_issuer,
                    "organization_claim_value": organization_claim_value,
                },
            )
        ).one_or_none()
        if row is None:
            return None
        return OidcTenantMapping(
            row.oidc_tenant_mapping_id,
            row.tenant_id,
            row.tenant_active,
            row.mapping_active,
        )

    async def external_identity(
        self, tenant_id: UUID, mapping_id: UUID, external_subject: str
    ) -> ExternalUserIdentity | None:
        row = (
            await self._session.execute(
                _EXTERNAL_IDENTITY,
                {
                    "tenant_id": tenant_id,
                    "mapping_id": mapping_id,
                    "external_subject": external_subject,
                },
            )
        ).one_or_none()
        if row is None:
            return None
        return ExternalUserIdentity(
            row.external_identity_id,
            row.external_identity_active,
            UserIdentity(
                row.user_id,
                row.tenant_id,
                row.external_subject,
                row.display_name,
                row.email_address,
                row.locale_code,
                row.business_unit_id,
                row.active_flag,
            ),
        )

    async def create_jit_user(
        self,
        tenant_id: UUID,
        external_subject: str,
        email_address: str,
        display_name: str,
        locale_code: str,
    ) -> UserIdentity:
        row = (
            await self._session.execute(
                _CREATE_JIT_USER,
                {
                    "tenant_id": tenant_id,
                    "external_subject": external_subject,
                    "email_address": email_address,
                    "display_name": display_name,
                    "locale_code": locale_code,
                },
            )
        ).one()
        return UserIdentity(
            row.user_id,
            row.tenant_id,
            row.external_subject,
            row.display_name,
            row.email_address,
            row.locale_code,
            row.business_unit_id,
            row.active_flag,
        )

    async def create_external_identity(
        self,
        tenant_id: UUID,
        mapping_id: UUID,
        user_id: UUID,
        external_subject: str,
        safe_metadata: dict[str, str | bool],
    ) -> UUID:
        result = await self._session.execute(
            _CREATE_EXTERNAL_IDENTITY,
            {
                "tenant_id": tenant_id,
                "mapping_id": mapping_id,
                "user_id": user_id,
                "external_subject": external_subject,
                "safe_metadata": json.dumps(safe_metadata, separators=(",", ":")),
            },
        )
        return cast("UUID", result.scalar_one())

    async def synchronize_profile(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        display_name: str | None,
        email_address: str | None,
        locale_code: str | None,
    ) -> bool:
        result = await self._session.execute(
            _SYNC_PROFILE,
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "display_name": display_name,
                "email_address": email_address,
                "locale_code": locale_code,
            },
        )
        return result.one_or_none() is not None

    async def touch_external_identity(
        self,
        external_identity_id: UUID,
        *,
        synchronized: bool,
        safe_metadata: dict[str, str | bool],
    ) -> None:
        await self._session.execute(
            _TOUCH_EXTERNAL_IDENTITY,
            {
                "external_identity_id": external_identity_id,
                "synchronized": synchronized,
                "safe_metadata": json.dumps(safe_metadata, separators=(",", ":")),
            },
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
