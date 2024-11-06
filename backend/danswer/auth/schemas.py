import uuid
from enum import Enum

from fastapi_users import schemas


class UserRole(str, Enum):
    """
    User roles
    - Basic can't perform any admin actions
    - Admin can perform all admin actions
    - Curator can perform admin actions for
        groups they are curators of
    - Global Curator can perform admin actions
        for all groups they are a member of
    """

    BASIC = "basic"
    ADMIN = "admin"
    CURATOR = "curator"
    GLOBAL_CURATOR = "global_curator"


class UserStatus(str, Enum):
    LIVE = "live"
    INVITED = "invited"
    DEACTIVATED = "deactivated"


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: UserRole


class UserCreate(schemas.BaseUserCreate):
    role: UserRole = UserRole.BASIC
    has_web_login: bool | None = True
    tenant_id: str | None = None


class UserUpdate(schemas.BaseUserUpdate):
    role: UserRole
    has_web_login: bool | None = True
