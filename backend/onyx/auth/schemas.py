import uuid
from enum import Enum
from typing import Any

from fastapi_users import schemas
from typing_extensions import override

from onyx.db.enums import AccountType


class UserRole(str, Enum):
    """Legacy tombstone: kept only as the column type for ``User.role``, which is never
    read or written. Authorization lives in ``Permission``, classification in
    ``AccountType``."""

    LIMITED = "limited"
    BASIC = "basic"
    ADMIN = "admin"
    CURATOR = "curator"
    GLOBAL_CURATOR = "global_curator"
    SLACK_USER = "slack_user"
    EXT_PERM_USER = "ext_perm_user"


class UserRead(schemas.BaseUser[uuid.UUID]):
    account_type: AccountType


class UserCreate(schemas.BaseUserCreate):
    account_type: AccountType = AccountType.STANDARD
    tenant_id: str | None = None
    # Captcha token for cloud signup protection (optional, only used when captcha is enabled)
    # Excluded from create_update_dict so it never reaches the DB layer
    captcha_token: str | None = None

    @override
    def create_update_dict(self) -> dict[str, Any]:
        d = super().create_update_dict()
        d.pop("captcha_token", None)
        # Force STANDARD for self-registration; only trusted paths
        # (SCIM, API key creation) supply a different account_type directly.
        d["account_type"] = AccountType.STANDARD
        return d

    @override
    def create_update_dict_superuser(self) -> dict[str, Any]:
        d = super().create_update_dict_superuser()
        d.pop("captcha_token", None)
        d.setdefault("account_type", self.account_type)
        return d


class UserUpdate(schemas.BaseUserUpdate):
    """Intentionally empty: keeps account_type and permissions out of the
    fastapi-users PATCH endpoints."""


class AuthBackend(str, Enum):
    REDIS = "redis"
    POSTGRES = "postgres"
    JWT = "jwt"
