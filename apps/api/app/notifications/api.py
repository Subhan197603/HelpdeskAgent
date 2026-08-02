"""Authenticated in-app notification endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.notifications.schemas import NotificationItem, NotificationList
from apps.api.app.notifications.service import NotificationService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Notification not found"},
}
router = APIRouter(prefix="/api/v1/my/notifications", tags=["notifications"])


def _service(request: Request) -> NotificationService:
    return cast("NotificationService", request.app.state.notification_service)


@router.get("", response_model=NotificationList, responses=ERRORS)
async def notifications(
    request: Request,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.NOTIFICATION_READ_OWN))
    ],
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> NotificationList:
    return await _service(request).mine(context, unread_only=unread_only, limit=limit)


@router.post("/{notification_id}/read", response_model=NotificationItem, responses=ERRORS)
async def mark_notification_read(
    request: Request,
    notification_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.NOTIFICATION_UPDATE_OWN))
    ],
) -> NotificationItem:
    return await _service(request).mark_read(context, notification_id)
