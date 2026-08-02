"""Minimal protected endpoints for validating the identity foundation."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import NotFoundError
from apps.api.app.core.settings import Settings
from apps.api.app.dependencies.request_context import (
    get_authenticated_identity,
    require_permission,
)
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.identity.models import AuthenticatedIdentity
from apps.api.app.identity.oidc import AuthenticationMetrics
from apps.api.app.identity.schemas import CurrentIdentityResponse, IdentityDiagnosticResponse

router = APIRouter(prefix="/api/v1", tags=["identity"])


async def require_identity_diagnostics_enabled(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if settings.is_production and not settings.oidc_diagnostics_enabled:
        raise NotFoundError("Resource not found.")


@router.get("/me", response_model=CurrentIdentityResponse)
async def current_identity(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.IDENTITY_SELF_READ))],
) -> CurrentIdentityResponse:
    identity: AuthenticatedIdentity = get_authenticated_identity(request)
    if context.user_id is None or context.tenant_id is None:
        raise RuntimeError("Authenticated request context is incomplete")
    return CurrentIdentityResponse(
        user_id=context.user_id,
        tenant_id=context.tenant_id,
        display_name=identity.display_name,
        business_unit_id=context.business_unit_id,
        business_unit_name=identity.business_unit_name,
        role_codes=sorted(context.roles),
        permission_codes=sorted(
            permission.value for permission in AuthorizationService().permissions_for(context)
        ),
        support_group_ids=sorted(context.support_group_ids, key=str),
        authentication_mode=identity.authentication_mode,
        provider_code=identity.provider_code,
    )


@router.get("/identity/diagnostics", response_model=IdentityDiagnosticResponse)
async def identity_diagnostics(
    request: Request,
    __: Annotated[None, Depends(require_identity_diagnostics_enabled)],
    _: Annotated[
        RequestContext,
        Depends(
            require_permission(
                Permission.ADMIN_IDENTITY_READ,
                privileged_access=True,
            )
        ),
    ],
) -> IdentityDiagnosticResponse:
    settings: Settings = request.app.state.settings
    identity = get_authenticated_identity(request)
    metrics: AuthenticationMetrics = request.app.state.authentication_metrics
    return IdentityDiagnosticResponse(
        status="authorized",
        authentication_mode=identity.authentication_mode,
        provider_code=identity.provider_code,
        oidc_enabled=settings.oidc_enabled,
        issuer_configured=bool(settings.oidc_issuer_url),
        audience_configured=bool(settings.oidc_audience),
        allowed_algorithms=settings.oidc_allowed_algorithms,
        jit_provisioning_enabled=settings.oidc_jit_provisioning_enabled,
        profile_synchronization_enabled=settings.oidc_profile_synchronization_enabled,
        group_synchronization_enabled=settings.oidc_group_synchronization_enabled,
        metrics=cast("dict[str, object]", metrics.snapshot()),
    )
