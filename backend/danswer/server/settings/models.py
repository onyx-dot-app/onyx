from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from danswer.configs.constants import NotificationType
from danswer.db.models import Notification as NotificationDBModel


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

    chat_page_enabled: bool = True
    search_page_enabled: bool = True
    default_page: PageType = PageType.SEARCH
    maximum_chat_retention_days: int | None = None
    gpu_enabled: bool | None = None
    product_gating: GatingType = GatingType.NONE

    def check_validity(self) -> None:
        chat_page_enabled = self.chat_page_enabled
        search_page_enabled = self.search_page_enabled
        default_page = self.default_page

        if chat_page_enabled is False and search_page_enabled is False:
            raise ValueError(
                "One of `search_page_enabled` and `chat_page_enabled` must be True."
            )

        if default_page == PageType.CHAT and chat_page_enabled is False:
            raise ValueError(
                "The default page cannot be 'chat' if the chat page is disabled."
            )

        if default_page == PageType.SEARCH and search_page_enabled is False:
            raise ValueError(
                "The default page cannot be 'search' if the search page is disabled."
            )


class UserSettings(Settings):
    notifications: list[Notification]
    needs_reindexing: bool
