from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr

from fastapi_users import models

SCHEMA = TypeVar("SCHEMA", bound=BaseModel)


class CreateUpdateDictModel(BaseModel):
    def create_update_dict(self):
        return self.model_dump(
            exclude_unset=True,
            exclude={
                "id",
                "is_superuser",
                "is_active",
                "is_verified",
                "oauth_accounts",
            },
        )

    def create_update_dict_superuser(self):
        return self.model_dump(exclude_unset=True, exclude={"id"})


class BaseUser(CreateUpdateDictModel, Generic[models.ID]):
    """Base User model."""

    id: models.ID
    email: EmailStr
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False

    model_config = ConfigDict(from_attributes=True)


class BaseUserCreate(CreateUpdateDictModel):
    email: EmailStr
    password: str
    is_active: bool | None = True
    is_superuser: bool | None = False
    is_verified: bool | None = False


class BaseUserUpdate(CreateUpdateDictModel):
    password: str | None = None
    email: EmailStr | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    is_verified: bool | None = None


U = TypeVar("U", bound=BaseUser)
UC = TypeVar("UC", bound=BaseUserCreate)
UU = TypeVar("UU", bound=BaseUserUpdate)


class BaseOAuthAccount(BaseModel, Generic[models.ID]):
    """Base OAuth account model."""

    id: models.ID
    oauth_name: str
    access_token: str
    expires_at: int | None = None
    refresh_token: str | None = None
    account_id: str
    account_email: str

    model_config = ConfigDict(from_attributes=True)


class BaseOAuthAccountMixin(BaseModel):
    """Adds OAuth accounts list to a User model."""

    oauth_accounts: list[BaseOAuthAccount] = []
