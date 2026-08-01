"""OIDC authentication, tenant resolution, synchronization, and JIT orchestration."""

import hashlib
from collections.abc import Callable
from uuid import UUID

from apps.api.app.audit.security_events import SecurityEvent, SecurityEventService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthenticationError
from apps.api.app.core.settings import Settings
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.models import AuthenticatedIdentity, UserIdentity
from apps.api.app.identity.oidc import (
    AuthenticationMetrics,
    OidcAuthenticationError,
    OidcFailureReason,
    OidcProviderError,
    OidcTokenValidator,
    ValidatedOidcIdentity,
)
from apps.api.app.identity.repository import IdentityRepository

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class OidcIdentityService:
    def __init__(
        self,
        settings: Settings,
        validator: OidcTokenValidator,
        unit_of_work_factory: UnitOfWorkFactory,
        metrics: AuthenticationMetrics,
    ) -> None:
        self._settings = settings
        self._validator = validator
        self._unit_of_work_factory = unit_of_work_factory
        self._metrics = metrics

    @staticmethod
    def _subject_hash(identity: ValidatedOidcIdentity) -> str:
        material = f"{identity.issuer}\0{identity.subject}".encode()
        return hashlib.sha256(material).hexdigest()[:24]

    @classmethod
    def _application_subject(cls, identity: ValidatedOidcIdentity) -> str:
        return f"oidc:{identity.provider_code}:{cls._subject_hash(identity)}"

    async def _record_anonymous(
        self, context: RequestContext, event_type: str, decision: str, reason: str
    ) -> None:
        async with self._unit_of_work_factory(context) as unit_of_work:
            await SecurityEventService(unit_of_work.session).record(
                SecurityEvent(
                    event_type,
                    decision,
                    details={
                        "provider_code": self._settings.oidc_provider_code or "unconfigured",
                        "reason_code": reason,
                    },
                    authentication_mode="oidc",
                ),
                context,
            )
            await unit_of_work.commit()

    async def authenticate(
        self, token: str, anonymous_context: RequestContext
    ) -> AuthenticatedIdentity:
        try:
            identity = await self._validator.validate(token)
        except OidcAuthenticationError as exc:
            await self._record_anonymous(
                anonymous_context,
                _validation_event_type(exc.reason),
                "DENIED",
                exc.reason.value,
            )
            raise
        except OidcProviderError:
            self._metrics.failures["provider_unavailable"] += 1
            await self._record_anonymous(
                anonymous_context,
                "OIDC_PROVIDER_DEPENDENCY_FAILED",
                "FAILED",
                "discovery_or_jwks_failure",
            )
            raise

        async with self._unit_of_work_factory(anonymous_context) as unit_of_work:
            repository = IdentityRepository(unit_of_work.session)
            events = SecurityEventService(unit_of_work.session)
            mapping = await repository.oidc_tenant_mapping(
                identity.provider_code, identity.issuer, identity.organization
            )
            if mapping is None:
                self._metrics.failures["tenant_mapping_not_found"] += 1
                await events.record(
                    _oidc_event(
                        "OIDC_TENANT_MAPPING_FAILED",
                        "DENIED",
                        identity,
                        reason="tenant_mapping_not_found",
                    ),
                    anonymous_context,
                )
                await unit_of_work.commit()
                raise _invalid_identity()

            tenant_context = RequestContext(
                mapping.tenant_id,
                None,
                None,
                frozenset(),
                frozenset(),
                None,
                anonymous_context.correlation_id,
                anonymous_context.request_id,
            )
            await apply_transaction_context(
                unit_of_work.session,
                tenant_context,
                rls_enabled=self._settings.rls_enabled,
            )
            if not mapping.mapping_active or not mapping.tenant_active:
                reason = "inactive_mapping" if not mapping.mapping_active else "inactive_tenant"
                self._metrics.failures[reason] += 1
                await events.record(
                    _oidc_event(
                        "OIDC_INACTIVE_TENANT",
                        "DENIED",
                        identity,
                        tenant_id=mapping.tenant_id,
                        reason=reason,
                    ),
                    tenant_context,
                )
                await unit_of_work.commit()
                raise _invalid_identity()

            external = await repository.external_identity(
                mapping.tenant_id, mapping.mapping_id, identity.subject
            )
            jit_created = False
            if external is None:
                if not self._settings.oidc_jit_provisioning_enabled:
                    self._metrics.failures["external_identity_unknown"] += 1
                    await events.record(
                        _oidc_event(
                            "OIDC_EXTERNAL_IDENTITY_UNKNOWN",
                            "DENIED",
                            identity,
                            tenant_id=mapping.tenant_id,
                            reason="jit_disabled",
                        ),
                        tenant_context,
                    )
                    await unit_of_work.commit()
                    raise _invalid_identity()
                if _valid_email(identity.email) is None:
                    self._metrics.failures["jit_profile_incomplete"] += 1
                    await events.record(
                        _oidc_event(
                            "OIDC_EXTERNAL_IDENTITY_UNKNOWN",
                            "DENIED",
                            identity,
                            tenant_id=mapping.tenant_id,
                            reason="jit_profile_incomplete",
                        ),
                        tenant_context,
                    )
                    await unit_of_work.commit()
                    raise _invalid_identity()
                user = await self._create_jit_user(repository, mapping.tenant_id, identity)
                external_id = await repository.create_external_identity(
                    mapping.tenant_id,
                    mapping.mapping_id,
                    user.user_id,
                    identity.subject,
                    _safe_metadata(identity),
                )
                jit_created = True
                self._metrics.jit_provisioned += 1
                await events.record(
                    _oidc_event(
                        "OIDC_JIT_USER_CREATED",
                        "ALLOWED",
                        identity,
                        tenant_id=mapping.tenant_id,
                        user_id=user.user_id,
                    ),
                    tenant_context,
                )
            else:
                external_id = external.external_identity_id
                user = external.user
                if not external.external_identity_active:
                    self._metrics.failures["external_identity_inactive"] += 1
                    await events.record(
                        _oidc_event(
                            "OIDC_EXTERNAL_IDENTITY_UNKNOWN",
                            "DENIED",
                            identity,
                            tenant_id=mapping.tenant_id,
                            reason="external_identity_inactive",
                        ),
                        tenant_context,
                    )
                    await unit_of_work.commit()
                    raise _invalid_identity()

            if not user.active:
                self._metrics.failures["inactive_user"] += 1
                await events.record(
                    _oidc_event(
                        "OIDC_USER_INACTIVE",
                        "DENIED",
                        identity,
                        tenant_id=mapping.tenant_id,
                        user_id=user.user_id,
                    ),
                    tenant_context,
                )
                await unit_of_work.commit()
                raise _invalid_identity()

            synchronized = False
            if self._settings.oidc_profile_synchronization_enabled and not jit_created:
                synchronized = await repository.synchronize_profile(
                    mapping.tenant_id,
                    user.user_id,
                    display_name=identity.display_name,
                    email_address=_valid_email(identity.email),
                    locale_code=identity.locale,
                )
                if synchronized:
                    self._metrics.profiles_synchronized += 1
                    await events.record(
                        _oidc_event(
                            "OIDC_PROFILE_SYNCHRONIZED",
                            "ALLOWED",
                            identity,
                            tenant_id=mapping.tenant_id,
                            user_id=user.user_id,
                        ),
                        tenant_context,
                    )
            await repository.touch_external_identity(
                external_id,
                synchronized=synchronized or jit_created,
                safe_metadata=_safe_metadata(identity),
            )

            roles = await repository.effective_roles(mapping.tenant_id, user.user_id)
            support_groups = await repository.effective_support_group_ids(
                mapping.tenant_id, user.user_id
            )
            business_unit = await repository.active_business_unit(
                mapping.tenant_id, user.business_unit_id
            )
            context = RequestContext(
                mapping.tenant_id,
                user.user_id,
                identity.subject,
                roles,
                support_groups,
                business_unit.business_unit_id if business_unit else None,
                anonymous_context.correlation_id,
                anonymous_context.request_id,
            )
            await apply_transaction_context(
                unit_of_work.session, context, rls_enabled=self._settings.rls_enabled
            )
            await events.record(
                _oidc_event(
                    "OIDC_AUTHENTICATION_SUCCEEDED",
                    "ALLOWED",
                    identity,
                    tenant_id=mapping.tenant_id,
                    user_id=user.user_id,
                ),
                context,
            )
            await unit_of_work.commit()
            self._metrics.successes += 1
            return AuthenticatedIdentity(
                context,
                (
                    identity.display_name
                    if self._settings.oidc_profile_synchronization_enabled or jit_created
                    else user.display_name
                )
                or user.display_name,
                business_unit.business_unit_name if business_unit else None,
                authentication_mode="oidc",
                provider_code=identity.provider_code,
            )

    async def _create_jit_user(
        self,
        repository: IdentityRepository,
        tenant_id: UUID,
        identity: ValidatedOidcIdentity,
    ) -> UserIdentity:
        email = _valid_email(identity.email)
        if email is None:
            raise RuntimeError("JIT provisioning requires an email claim")
        return await repository.create_jit_user(
            tenant_id,
            self._application_subject(identity),
            email,
            identity.display_name or "OIDC User",
            identity.locale or "en",
        )


def _valid_email(value: str | None) -> str | None:
    return value if value is not None and "@" in value and not value.startswith("@") else None


def _safe_metadata(identity: ValidatedOidcIdentity) -> dict[str, str | bool]:
    return {
        "provider_code": identity.provider_code,
        "groups_observed": bool(identity.external_groups),
    }


def _oidc_event(
    event_type: str,
    decision: str,
    identity: ValidatedOidcIdentity,
    *,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    reason: str | None = None,
) -> SecurityEvent:
    details = {
        "provider_code": identity.provider_code,
        "subject_hash": OidcIdentityService._subject_hash(identity),
    }
    if reason:
        details["reason_code"] = reason
    return SecurityEvent(
        event_type,
        decision,
        tenant_id=tenant_id,
        user_id=user_id,
        resource_type="user" if user_id else None,
        resource_id=str(user_id) if user_id else None,
        details=details,
        authentication_mode="oidc",
    )


def _validation_event_type(reason: OidcFailureReason) -> str:
    return {
        OidcFailureReason.INCORRECT_ISSUER: "OIDC_ISSUER_REJECTED",
        OidcFailureReason.INCORRECT_AUDIENCE: "OIDC_AUDIENCE_REJECTED",
        OidcFailureReason.INVALID_SIGNATURE: "OIDC_SIGNATURE_REJECTED",
        OidcFailureReason.EXPIRED_TOKEN: "OIDC_TOKEN_EXPIRED",
    }.get(reason, "OIDC_TOKEN_REJECTED")


def _invalid_identity() -> AuthenticationError:
    return AuthenticationError(
        "Bearer token is invalid.",
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )
