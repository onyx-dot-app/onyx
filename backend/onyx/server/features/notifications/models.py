from datetime import datetime
from typing import Any

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from onyx.configs.constants import NotificationType


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    notif_type: NotificationType
    dismissed: bool
    last_shown: datetime
    version: datetime = Field(validation_alias="last_shown")
    first_shown: datetime
    title: str
    description: str | None = None
    additional_data: dict[str, Any] | None = None


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


class DismissNotificationRequest(BaseModel):
    expected_version: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("expected_version", "expected_last_shown"),
    )
