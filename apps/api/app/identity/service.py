"""Development-only identity orchestration and security-event recording."""

import re
from collections.abc import Callable

from apps.api.app.audit.security_events import SecurityEvent, SecurityEventService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthenticationError
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.models import AuthenticatedIdentity
from apps.api.app.identity.repository import IdentityRepository

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]
_TENANT_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")
_EXTERNAL_SUBJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@:-]{0,299}$")


class DeveloperIdentityService:
    """Resolve a controlled local selector into database-authoritative identity data."""

    def __init__(self, unit_of_work_factory: UnitOfWorkFactory, *, rls_enabled: bool) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._rls_enabled = rls_enabled

    @staticmethod
    def _parse_selector(selector: str) -> tuple[str, str] | None:
        tenant_code, separator, external_subject = selector.partition("/")
        if (
            separator != "/"
            or not _TENANT_CODE.fullmatch(tenant_code)
            or not _EXTERNAL_SUBJECT.fullmatch(external_subject)
        ):
            return None
        return tenant_code, external_subject

    async def authenticate(
        self, selector: str, anonymous_context: RequestContext
    ) -> AuthenticatedIdentity:
        parsed = self._parse_selector(selector)
        if parsed is None:
            await self.record_event(
                anonymous_context,
                SecurityEvent("DEVELOPER_IDENTITY_UNKNOWN", "DENIED"),
            )
            raise AuthenticationError("Developer identity is invalid.")

        tenant_code, external_subject = parsed
        async with self._unit_of_work_factory(anonymous_context) as unit_of_work:
            identities = IdentityRepository(unit_of_work.session)
            security_events = SecurityEventService(unit_of_work.session)
            tenant = await identities.tenant_by_code(tenant_code)
            if tenant is None:
                await security_events.record(
                    SecurityEvent("DEVELOPER_IDENTITY_UNKNOWN", "DENIED"), anonymous_context
                )
                await unit_of_work.commit()
                raise AuthenticationError("Developer identity is invalid.")

            tenant_context = RequestContext(
                tenant.tenant_id,
                None,
                None,
                frozenset(),
                frozenset(),
                None,
                anonymous_context.correlation_id,
                anonymous_context.request_id,
            )
            await apply_transaction_context(
                unit_of_work.session, tenant_context, rls_enabled=self._rls_enabled
            )
            if not tenant.active:
                await security_events.record(
                    SecurityEvent(
                        "DEVELOPER_IDENTITY_INACTIVE",
                        "DENIED",
                        tenant_id=tenant.tenant_id,
                        resource_type="tenant",
                    ),
                    anonymous_context,
                )
                await unit_of_work.commit()
                raise AuthenticationError("Developer identity is invalid.")

            user = await identities.user_by_external_subject(tenant.tenant_id, external_subject)
            if user is None:
                await security_events.record(
                    SecurityEvent(
                        "DEVELOPER_IDENTITY_UNKNOWN",
                        "DENIED",
                        tenant_id=tenant.tenant_id,
                    ),
                    anonymous_context,
                )
                await unit_of_work.commit()
                raise AuthenticationError("Developer identity is invalid.")
            if not user.active:
                await security_events.record(
                    SecurityEvent(
                        "DEVELOPER_IDENTITY_INACTIVE",
                        "DENIED",
                        tenant_id=tenant.tenant_id,
                        user_id=user.user_id,
                        resource_type="user",
                        resource_id=str(user.user_id),
                    ),
                    anonymous_context,
                )
                await unit_of_work.commit()
                raise AuthenticationError("Developer identity is invalid.")

            roles = await identities.effective_roles(tenant.tenant_id, user.user_id)
            support_groups = await identities.effective_support_group_ids(
                tenant.tenant_id, user.user_id
            )
            business_unit = await identities.active_business_unit(
                tenant.tenant_id, user.business_unit_id
            )
            context = RequestContext(
                tenant.tenant_id,
                user.user_id,
                user.external_subject,
                roles,
                support_groups,
                business_unit.business_unit_id if business_unit else None,
                anonymous_context.correlation_id,
                anonymous_context.request_id,
            )
            await apply_transaction_context(
                unit_of_work.session, context, rls_enabled=self._rls_enabled
            )
            await security_events.record(
                SecurityEvent(
                    "DEVELOPER_AUTHENTICATION_SUCCEEDED",
                    "ALLOWED",
                    tenant_id=tenant.tenant_id,
                    user_id=user.user_id,
                    resource_type="user",
                    resource_id=str(user.user_id),
                ),
                context,
            )
            await unit_of_work.commit()
            return AuthenticatedIdentity(
                context=context,
                display_name=user.display_name,
                business_unit_name=(business_unit.business_unit_name if business_unit else None),
            )

    async def record_event(self, context: RequestContext, event: SecurityEvent) -> None:
        async with self._unit_of_work_factory(context) as unit_of_work:
            await SecurityEventService(unit_of_work.session).record(event, context)
            await unit_of_work.commit()
