from typing import Optional

from fastapi import Depends
from fastapi import Request
from fastapi_users import BaseUserManager
from fastapi_users import UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase

from onyx.auth.essential_user import EssentialUser
from onyx.auth.essential_user import get_essential_user_db
from onyx.configs.app_configs import USER_MANAGER_SECRET


class EssentialUserManager(UUIDIDMixin, BaseUserManager[EssentialUser, str]):
    """
    A simplified user manager that only handles essential authentication operations.
    This is used during the initial tenant setup phase to avoid errors with missing columns.
    """

    reset_password_token_secret = USER_MANAGER_SECRET
    verification_token_secret = USER_MANAGER_SECRET

    async def on_after_register(
        self, user: EssentialUser, request: Optional[Request] = None
    ) -> None:
        """
        Simplified post-registration hook.
        """

    async def on_after_forgot_password(
        self, user: EssentialUser, token: str, request: Optional[Request] = None
    ) -> None:
        """
        Simplified post-forgot-password hook.
        """

    async def on_after_request_verify(
        self, user: EssentialUser, token: str, request: Optional[Request] = None
    ) -> None:
        """
        Simplified post-verification-request hook.
        """


async def get_essential_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_essential_user_db),
) -> EssentialUserManager:
    """
    Get a user manager that uses the essential user model.
    This avoids errors with missing columns during the initial tenant setup.
    """
    yield EssentialUserManager(user_db)
