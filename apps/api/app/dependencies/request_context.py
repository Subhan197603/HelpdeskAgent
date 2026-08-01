"""Request-context, developer authentication, and permission dependencies."""

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.exc import SQLAlchemyError

from apps.api.app.audit.security_events import SecurityEvent
from apps.api.app.core.context import RequestContext, set_current_request_context
from apps.api.app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ExternalDependencyError,
)
from apps.api.app.core.settings import Settings
from apps.api.app.identity.authorization import (
    AuthorizationResource,
    AuthorizationService,
    Permission,
)
from apps.api.app.identity.models import AuthenticatedIdentity
from apps.api.app.identity.service import DeveloperIdentityService

logger = logging.getLogger(__name__)
_FORBIDDEN_IDENTITY_HEADERS = frozenset(
    {
        "x-tenant-id",
        "x-user-id",
        "x-roles",
        "x-permissions",
        "x-support-group-ids",
        "x-business-unit-id",
    }
)


def get_request_context(request: Request) -> RequestContext:
    context = getattr(request.state, "request_context", None)
    if not isinstance(context, RequestContext):
        raise RuntimeError("Request context middleware is not installed")
    return context


def get_authenticated_identity(request: Request) -> AuthenticatedIdentity:
    identity = getattr(request.state, "authenticated_identity", None)
    if not isinstance(identity, AuthenticatedIdentity):
        raise RuntimeError("Authenticated identity dependency has not run")
    return identity


async def _record_or_fail(
    service: DeveloperIdentityService, context: RequestContext, event: SecurityEvent
) -> None:
    try:
        await service.record_event(context, event)
    except SQLAlchemyError:
        logger.exception("Security event persistence failed", extra={"error_code": "audit_failed"})
        raise ExternalDependencyError("Authentication service is unavailable.") from None


async def require_authenticated_context(request: Request) -> RequestContext:
    current = get_request_context(request)
    if current.is_authenticated:
        return current

    settings = cast(Settings, request.app.state.settings)
    service = cast(DeveloperIdentityService, request.app.state.developer_identity_service)
    selector = request.headers.get(settings.developer_identity_header)
    if not settings.developer_identity_enabled:
        if selector is not None:
            await _record_or_fail(
                service,
                current,
                SecurityEvent("DEVELOPER_IDENTITY_DISABLED_ATTEMPT", "DENIED"),
            )
        raise AuthenticationError("Authentication is required.")
    if selector is None:
        raise AuthenticationError("Authentication is required.")

    supplied_headers = {name.lower() for name in request.headers}
    if supplied_headers & _FORBIDDEN_IDENTITY_HEADERS:
        await _record_or_fail(
            service,
            current,
            SecurityEvent("DEVELOPER_IDENTITY_CONTEXT_INJECTION_ATTEMPT", "DENIED"),
        )
        raise AuthenticationError("Developer identity is invalid.")

    try:
        identity = await service.authenticate(selector, current)
    except AuthenticationError:
        raise
    except SQLAlchemyError:
        logger.exception("Developer identity lookup failed", extra={"error_code": "identity_db"})
        raise ExternalDependencyError("Authentication service is unavailable.") from None

    request.state.request_context = identity.context
    request.state.authenticated_identity = identity
    set_current_request_context(identity.context)
    return identity.context


def require_permission(
    permission: Permission,
    *,
    resource: AuthorizationResource | None = None,
    privileged_access: bool = False,
) -> Callable[..., Awaitable[RequestContext]]:
    async def dependency(
        request: Request,
        context: Annotated[RequestContext, Depends(require_authenticated_context)],
    ) -> RequestContext:
        authorization = cast(AuthorizationService, request.app.state.authorization_service)
        identity_service = cast(
            DeveloperIdentityService, request.app.state.developer_identity_service
        )
        if not authorization.is_allowed(context, permission, resource):
            await _record_or_fail(
                identity_service,
                context,
                SecurityEvent(
                    "AUTHORIZATION_DENIED",
                    "DENIED",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    resource_type="permission",
                    resource_id=permission.value,
                ),
            )
            raise AuthorizationError(
                "The authenticated user is not permitted to access this resource."
            )
        if privileged_access:
            await _record_or_fail(
                identity_service,
                context,
                SecurityEvent(
                    "PRIVILEGED_ENDPOINT_ACCESSED",
                    "ALLOWED",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    resource_type="permission",
                    resource_id=permission.value,
                ),
            )
        return context

    return dependency
