from typing import Generic
from typing import Optional
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel

from onyx.auth.schemas import UserRole
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


class FullUserSnapshot(BaseModel):
    id: UUID
    email: str
    role: UserRole
    is_active: bool
    password_configured: bool

    @classmethod
    def from_user_model(cls, user: User) -> "FullUserSnapshot":
        return cls(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            password_configured=user.password_configured,
        )


class DisplayPriorityRequest(BaseModel):
    display_priority_map: dict[int, int]


class InvitedUserSnapshot(BaseModel):
    email: str
