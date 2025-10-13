from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from onyx.configs.constants import NotificationType
from onyx.configs.constants import QueryHistoryType
from onyx.db.models import Notification as NotificationDBModel
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA


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

    # is float to allow for fractional days for easier automated testing
    maximum_chat_retention_days: float | None = None
    company_name: str | None = None
    company_description: str | None = None
    gpu_enabled: bool | None = None
    application_status: ApplicationStatus = ApplicationStatus.ACTIVE
    anonymous_user_enabled: bool | None = None
    deep_research_enabled: bool | None = None

    temperature_override_enabled: bool | None = False
    auto_scroll: bool | None = False
    query_history_type: QueryHistoryType | None = None

    # Image processing settings
    image_extraction_and_analysis_enabled: bool | None = False
    search_time_image_analysis_enabled: bool | None = False
    image_analysis_max_size_mb: int | None = 20

    # User Knowledge settings
    user_knowledge_enabled: bool | None = True

    # Connector settings
    show_extra_connectors: bool | None = True


class UserSettings(Settings):
    notifications: list[Notification]
    needs_reindexing: bool
    tenant_id: str = POSTGRES_DEFAULT_SCHEMA
