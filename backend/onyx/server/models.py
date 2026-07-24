import datetime
from typing import Generic, Optional, TypeVar
from uuid import UUID

from pydantic import BaseModel

from onyx.auth.schemas import UserRole
from onyx.db.enums import AccountType
from onyx.db.models import User

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
    # User.personal_name, or None when unset. Callers fall back to email.
    personal_name: str | None = None


class UserGroupInfo(BaseModel):
    id: int
    name: str


class FullUserSnapshot(BaseModel):
    id: UUID
    email: str
    role: UserRole
    account_type: AccountType
    is_active: bool
    password_configured: bool
    personal_name: str | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
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
    ) -> "FullUserSnapshot":
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            account_type=user.account_type,
            is_active=user.is_active,
            password_configured=user.password_configured,
            personal_name=user.personal_name,
            created_at=user.created_at,
            updated_at=user.updated_at,
            groups=groups or [],
            is_scim_synced=is_scim_synced,
            craft_enabled=user.craft_enabled,
        )


class DisplayPriorityRequest(BaseModel):
    display_priority_map: dict[int, int]


class InvitedUserSnapshot(BaseModel):
    email: str
