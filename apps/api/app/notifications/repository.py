"""Tenant-scoped in-app notification persistence."""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.notifications.models import InAppNotification


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(
        self, tenant_id: UUID, user_id: UUID, *, unread_only: bool, limit: int
    ) -> list[InAppNotification]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT in_app_notification_id,resource_type,resource_id,title,body,
                      action_url,created_at,read_at
                    FROM integration.in_app_notification
                    WHERE tenant_id=:tenant_id AND recipient_user_id=:user_id
                      AND (NOT :unread_only OR read_at IS NULL)
                    ORDER BY created_at DESC,in_app_notification_id DESC
                    LIMIT :limit
                """),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "unread_only": unread_only,
                    "limit": limit,
                },
            )
        ).all()
        return [InAppNotification(*tuple(row)) for row in rows]

    async def unread_count(self, tenant_id: UUID, user_id: UUID) -> int:
        value = await self._session.scalar(
            text("""
                SELECT count(*) FROM integration.in_app_notification
                WHERE tenant_id=:tenant_id AND recipient_user_id=:user_id
                  AND read_at IS NULL
            """),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
        return int(value or 0)

    async def mark_read(
        self, tenant_id: UUID, user_id: UUID, notification_id: UUID
    ) -> InAppNotification | None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE integration.in_app_notification
                    SET read_at=coalesce(read_at,clock_timestamp())
                    WHERE tenant_id=:tenant_id AND recipient_user_id=:user_id
                      AND in_app_notification_id=:notification_id
                    RETURNING in_app_notification_id,resource_type,resource_id,title,body,
                      action_url,created_at,read_at
                """),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "notification_id": notification_id,
                },
            )
        ).one_or_none()
        return InAppNotification(*tuple(row)) if row is not None else None
