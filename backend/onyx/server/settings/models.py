from datetime import datetime
from enum import Enum

from pydantic import BaseModel
from pydantic import Field

from onyx.configs.app_configs import DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.app_configs import MAX_ALLOWED_UPLOAD_SIZE_MB
from onyx.configs.constants import NotificationType
from onyx.configs.constants import QueryHistoryType
from onyx.db.models import Notification as NotificationDBModel
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_VECTOR_DB = 200
DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_NO_VECTOR_DB = 10000


class PageType(str, Enum):
    CHAT = "chat"
    SEARCH = "search"


class ApplicationStatus(str, Enum):
    ACTIVE = "active"
    PAYMENT_REMINDER = "payment_reminder"
    GRACE_PERIOD = "grace_period"
    GATED_ACCESS = "gated_access"
    SEAT_LIMIT_EXCEEDED = "seat_limit_exceeded"


class Notification(BaseModel):
    id: int
    notif_type: NotificationType
    dismissed: bool
    last_shown: datetime
    first_shown: datetime
    title: str
    description: str | None = None
    additional_data: dict | None = None

    @classmethod
    def from_model(cls, notif: NotificationDBModel) -> "Notification":
        return cls(
            id=notif.id,
            notif_type=notif.notif_type,
            dismissed=notif.dismissed,
            last_shown=notif.last_shown,
            first_shown=notif.first_shown,
            title=notif.title,
            description=notif.description,
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
    invite_only_enabled: bool = False
    deep_research_enabled: bool | None = None
    multi_model_chat_enabled: bool | None = True
    search_ui_enabled: bool | None = True

    # Whether EE features are unlocked for use.
    # Depends on license status: True when the user has a valid license
    # (ACTIVE, GRACE_PERIOD, PAYMENT_REMINDER), False when there's no license
    # or the license is expired (GATED_ACCESS).
    # This controls UI visibility of EE features (user groups, analytics, RBAC, etc.).
    ee_features_enabled: bool = False

    temperature_override_enabled: bool | None = False
    auto_scroll: bool | None = False
    query_history_type: QueryHistoryType | None = None

    # Image processing settings
    image_extraction_and_analysis_enabled: bool | None = False
    search_time_image_analysis_enabled: bool | None = False
    image_analysis_max_size_mb: int | None = 20

    # User Knowledge settings
    user_knowledge_enabled: bool | None = True
    user_file_max_upload_size_mb: int | None = Field(
        default=DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB, ge=0
    )
    file_token_count_threshold_k: int | None = Field(
        default=None,
        ge=0,  # thousands of tokens; None = context-aware default
    )

    # Connector settings
    show_extra_connectors: bool | None = True

    # Default Assistant settings
    disable_default_assistant: bool | None = False

    # Seat usage - populated by license enforcement when seat limit is exceeded
    seat_count: int | None = None
    used_seats: int | None = None

    # OpenSearch migration
    opensearch_indexing_enabled: bool = False


class UserSettings(Settings):
    notifications: list[Notification]
    needs_reindexing: bool
    tenant_id: str = POSTGRES_DEFAULT_SCHEMA
    # Feature flag for Onyx Craft (Build Mode) - used for server-side redirects
    onyx_craft_enabled: bool = False
    # True when a vector database (Vespa/OpenSearch) is available.
    # False when DISABLE_VECTOR_DB is set — connectors, RAG search, and
    # document sets are unavailable.
    vector_db_enabled: bool = True
    # True when hooks are available: single-tenant EE deployments only.
    hooks_enabled: bool = False
    # Application version, read from the ONYX_VERSION env var at startup.
    version: str | None = None
    # Hard ceiling for user_file_max_upload_size_mb, derived from env var.
    max_allowed_upload_size_mb: int = MAX_ALLOWED_UPLOAD_SIZE_MB
    # Factory defaults so the frontend can show a "restore default" button.
    default_user_file_max_upload_size_mb: int = DEFAULT_USER_FILE_MAX_UPLOAD_SIZE_MB
    default_file_token_count_threshold_k: int = Field(
        default_factory=lambda: (
            DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_NO_VECTOR_DB
            if DISABLE_VECTOR_DB
            else DEFAULT_FILE_TOKEN_COUNT_THRESHOLD_K_VECTOR_DB
        )
    )
