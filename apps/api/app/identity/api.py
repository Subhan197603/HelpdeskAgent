"""Minimal protected endpoints for validating the identity foundation."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import (
    get_authenticated_identity,
    require_permission,
)
from apps.api.app.identity.authorization import Permission
from apps.api.app.identity.models import AuthenticatedIdentity
from apps.api.app.identity.schemas import CurrentIdentityResponse, IdentityDiagnosticResponse

router = APIRouter(prefix="/api/v1", tags=["identity"])


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
        support_group_ids=sorted(context.support_group_ids, key=str),
        authentication_mode="developer_header",
    )


@router.get("/identity/diagnostics", response_model=IdentityDiagnosticResponse)
async def identity_diagnostics(
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
    return IdentityDiagnosticResponse(status="authorized", authentication_mode="developer_header")
