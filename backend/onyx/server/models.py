import datetime
from enum import Enum
from typing import Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from onyx.db.enums import AccountType, UsageType, WindowAnchor
from onyx.db.models import User
from onyx.server.tenant_usage_limits import TenantUsageLimitKeys

DataT = TypeVar("DataT")


class StatusResponse(BaseModel, Generic[DataT]):
    success: bool
    message: Optional[str] = None
    data: Optional[DataT] = None


class ApiKey(BaseModel):
    api_key: str


class IdReturn(BaseModel):
    id: int


class MinimalUserSnapshot(BaseModel):
    id: UUID
    email: str


class UserGroupInfo(BaseModel):
    id: int
    name: str


class FullUserSnapshot(BaseModel):
    id: UUID
    email: str
    account_type: AccountType
    is_admin: bool = False
    is_active: bool
    password_configured: bool
    personal_name: str | None
    profile_image_file_id: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    # Most recent chat activity. None when the user has never chatted. Distinct
    # from `updated_at`, which only moves when the user row itself is written.
    last_active: datetime.datetime | None = None
    groups: list[UserGroupInfo]
    is_scim_synced: bool
    # Per-user Craft override; None = follow the workspace default.
    craft_enabled: bool | None

    @classmethod
    def from_user_model(
        cls,
        user: User,
        groups: list[UserGroupInfo] | None = None,
        is_scim_synced: bool = False,
        is_admin: bool = False,
        last_active: datetime.datetime | None = None,
    ) -> "FullUserSnapshot":
        return cls(
            id=user.id,
            email=user.email,
            account_type=user.account_type,
            is_admin=is_admin,
            is_active=user.is_active,
            password_configured=user.password_configured,
            personal_name=user.personal_name,
            profile_image_file_id=user.profile_image_file_id,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_active=last_active,
            groups=groups or [],
            is_scim_synced=is_scim_synced,
            craft_enabled=user.craft_enabled,
        )


class DisplayPriorityRequest(BaseModel):
    display_priority_map: dict[int, int]


class InvitedUserSnapshot(BaseModel):
    email: str


"""
Tenant usage limit policies (enforced in ``onyx.server.usage_limits``)
"""


class LimitScope(str, Enum):
    """Whose usage a limit counts."""

    TENANT = "tenant"


class LimitMeasure(str, Enum):
    """Where a limit's current usage is read from."""

    # A tenant_usage_counter row. Checked before the call, added after it, so one
    # call can pass the line; callers that need an exact stop pass the amount
    # they are about to use as ``pending_amount``.
    COUNTER = "counter"


class LimitWindow(BaseModel):
    """The period a limit's usage is counted over before it starts from zero."""

    model_config = ConfigDict(frozen=True)

    anchor: WindowAnchor
    # Length of one window. None means one window that never resets.
    length_seconds: int | None = None

    @model_validator(mode="after")
    def _calendar_has_length(self) -> "LimitWindow":
        if self.anchor == WindowAnchor.CALENDAR and self.length_seconds is None:
            raise ValueError("A calendar window needs a length")
        return self


class LimitPolicyName(str, Enum):
    """The plans a tenant can be held to. Fixed in code; one ``LimitPolicy`` each."""

    CLOUD_TRIAL = "cloud_trial"
    CLOUD_PAID = "cloud_paid"


class Allowance(BaseModel):
    """One usage type under one policy: how much, over what window, whose usage,
    read from where, and which override field can replace the amount."""

    model_config = ConfigDict(frozen=True)

    # NO_LIMIT for unlimited, 0 for nothing allowed.
    limit: int
    scope: LimitScope = LimitScope.TENANT
    measure: LimitMeasure = LimitMeasure.COUNTER
    # Required for a COUNTER; it picks the period the count is added up in.
    # Changing a counter's window starts its count again from 0: the new
    # period is a new row, and the usage counted under the old window is not
    # carried over (its rows stay, unread). Changing only ``limit`` keeps the
    # count. To carry usage over, add the old total into the new period's row
    # when the change ships, or read the old window's usage alongside the new.
    window: LimitWindow | None = None
    # Field of cloud's override record that replaces ``limit`` for one tenant.
    override_field: TenantUsageLimitKeys | None = None

    @model_validator(mode="after")
    def _counter_has_window(self) -> "Allowance":
        if self.measure == LimitMeasure.COUNTER and self.window is None:
            raise ValueError("A counter allowance needs a window")
        return self


class LimitPolicy(BaseModel):
    """Everything one plan allows. A usage type with no allowance is unlimited."""

    model_config = ConfigDict(frozen=True)

    name: LimitPolicyName
    allowances: dict[UsageType, Allowance]
