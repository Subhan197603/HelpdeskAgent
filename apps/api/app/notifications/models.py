"""Transport-independent in-app notification records."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InAppNotification:
    notification_id: UUID
    resource_type: str
    resource_id: str
    title: str
    body: str
    action_url: str | None
    created_at: datetime
    read_at: datetime | None
