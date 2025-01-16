from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from onyx.configs.constants import NotificationType
from onyx.db.models import Notification as NotificationDBModel


class PageType(str, Enum):
    CHAT = "chat"
    SEARCH = "search"


class GatingType(str, Enum):
    FULL = "full"  # Complete restriction of access to the product or service
    PARTIAL = "partial"  # Full access but warning (no credit card on file)
    NONE = "none"  # No restrictions, full access to all features


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
    product_gating: GatingType = GatingType.NONE
    anonymous_user_enabled: bool | None = None


class UserSettings(Settings):
    notifications: list[Notification]
    needs_reindexing: bool
    tenant_id: str | None = None
