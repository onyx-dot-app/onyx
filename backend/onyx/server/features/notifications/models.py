from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.configs.constants import NotificationType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notif_type: NotificationType
    dismissed: bool
    last_shown: datetime
    first_shown: datetime
    title: str
    description: str | None = None
    additional_data: dict | None = None


class PaginatedNotifications(BaseModel):
    notifications: list[NotificationResponse]
    total_items: int
    undismissed_count: int
    page_num: int
    page_size: int
    has_more: bool


class NotificationSummary(BaseModel):
    total_items: int
    undismissed_count: int
