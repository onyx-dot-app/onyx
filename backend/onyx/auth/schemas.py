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
    - Limited can access a limited set of basic api endpoints
    - Slack are users that have used onyx via slack but dont have a web login
    - External permissioned users that have been picked up during the external permissions sync process but don't have a web login
    """

    LIMITED = "limited"
    BASIC = "basic"
    ADMIN = "admin"
    CURATOR = "curator"
    GLOBAL_CURATOR = "global_curator"
    SLACK_USER = "slack_user"
    EXT_PERM_USER = "ext_perm_user"

    def is_web_login(self) -> bool:
        return self not in [
            UserRole.SLACK_USER,
            UserRole.EXT_PERM_USER,
        ]


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: UserRole


class UserCreate(schemas.BaseUserCreate):
    role: UserRole = UserRole.BASIC
    tenant_id: str | None = None


class UserUpdateWithRole(schemas.BaseUserUpdate):
    role: UserRole


class UserUpdate(schemas.BaseUserUpdate):
    """
    Role updates are not allowed through the user update endpoint for security reasons
    Role changes should be handled through a separate, admin-only process
    """


class AuthBackend(str, Enum):
    REDIS = "redis"
    POSTGRES = "postgres"
