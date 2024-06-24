import uuid
from enum import Enum

from fastapi_users import schemas


class UserRole(str, Enum):
    BASIC = "basic"
    ADMIN = "admin"


class UserStatus(str, Enum):
    LIVE = "live"
    INVITED = "invited"
    DEACTIVATED = "deactivated"


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: UserRole


class UserCreate(schemas.BaseUserCreate):
    role: UserRole = UserRole.BASIC


class UserUpdate(schemas.BaseUserUpdate):
    role: UserRole
