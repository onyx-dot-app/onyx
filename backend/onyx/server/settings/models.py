from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from onyx.configs.constants import NotificationType
from onyx.db.models import Notification as NotificationDBModel


class PageType(str, Enum):
    CHAT = "chat"
    SEARCH = "search"


class ApplicationStatus(str, Enum):
    PAYMENT_REMINDER = "payment_reminder"
    GATED_ACCESS = "gated_access"
    ACTIVE = "active"


class Notification(BaseModel):
    id: int
    notif_type: NotificationType
    dismissed: bool
    last_shown: datetime
    first_shown: datetime
    additional_data: dict | None = None

    @classmethod
    def from_model(cls, notif: NotificationDBModel) -> "Notification":
        return cls(
            id=notif.id,
            notif_type=notif.notif_type,
            dismissed=notif.dismissed,
            last_shown=notif.last_shown,
            first_shown=notif.first_shown,
            additional_data=notif.additional_data,
        )


class Settings(BaseModel):
    """General settings"""

    maximum_chat_retention_days: int | None = None
    gpu_enabled: bool | None = None
    application_status: ApplicationStatus = ApplicationStatus.ACTIVE
    anonymous_user_enabled: bool | None = None
    pro_search_disabled: bool | None = None

    temperature_override_enabled: bool = False
    auto_scroll: bool = False


class UserSettings(Settings):
    notifications: list[Notification]
    needs_reindexing: bool
    tenant_id: str | None = None
