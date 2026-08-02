"""In-app notification API contracts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationItem(BaseModel):
    id: UUID
    resource_type: str
    resource_id: str
    title: str
    body: str
    action_url: str | None
    created_at: datetime
    read_at: datetime | None
    unread: bool


class NotificationList(BaseModel):
    items: list[NotificationItem]
    unread_count: int
