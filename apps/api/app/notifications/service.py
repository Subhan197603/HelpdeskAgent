"""Authorized in-app notification use cases."""

from collections.abc import Callable
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, NotFoundError
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.notifications.models import InAppNotification
from apps.api.app.notifications.repository import NotificationRepository
from apps.api.app.notifications.schemas import NotificationItem, NotificationList

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class NotificationService:
    def __init__(self, factory: UnitOfWorkFactory, authorization: AuthorizationService) -> None:
        self._factory = factory
        self._authorization = authorization

    async def mine(
        self, context: RequestContext, *, unread_only: bool, limit: int
    ) -> NotificationList:
        tenant_id, user_id = self._identity(context, Permission.NOTIFICATION_READ_OWN)
        async with self._factory(context) as uow:
            repo = NotificationRepository(uow.session)
            items = await repo.list_for_user(
                tenant_id, user_id, unread_only=unread_only, limit=limit
            )
            unread_count = await repo.unread_count(tenant_id, user_id)
        return NotificationList(items=[_item(value) for value in items], unread_count=unread_count)

    async def mark_read(self, context: RequestContext, notification_id: UUID) -> NotificationItem:
        tenant_id, user_id = self._identity(context, Permission.NOTIFICATION_UPDATE_OWN)
        async with self._factory(context) as uow:
            value = await NotificationRepository(uow.session).mark_read(
                tenant_id, user_id, notification_id
            )
            if value is None:
                raise NotFoundError("Notification was not found.")
            await uow.commit()
        return _item(value)

    def _identity(self, context: RequestContext, permission: Permission) -> tuple[UUID, UUID]:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError(
                "The authenticated user is not permitted to access notifications."
            )
        if context.tenant_id is None or context.user_id is None:
            raise NotFoundError("Notification was not found.")
        return context.tenant_id, context.user_id


def _item(value: InAppNotification) -> NotificationItem:
    return NotificationItem(
        id=value.notification_id,
        resource_type=value.resource_type,
        resource_id=value.resource_id,
        title=value.title,
        body=value.body,
        action_url=value.action_url,
        created_at=value.created_at,
        read_at=value.read_at,
        unread=value.read_at is None,
    )
