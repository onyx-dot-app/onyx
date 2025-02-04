from collections.abc import AsyncGenerator
from collections.abc import Callable
from typing import Any
from typing import Dict

from fastapi import Depends
from fastapi_users.models import ID
from fastapi_users.models import UP
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from onyx.auth.invited_users import get_invited_users
from onyx.auth.schemas import UserRole
from onyx.db.api_key import get_api_key_email_pattern
from onyx.db.engine import get_async_session
from onyx.db.engine import get_async_session_with_tenant
from onyx.db.models import AccessToken
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)


def get_default_admin_user_emails() -> list[str]:
    """Returns a list of emails who should default to Admin role.
    Only used in the EE version. For MIT, just return empty list."""
    get_default_admin_user_emails_fn: Callable[
        [], list[str]
    ] = fetch_versioned_implementation_with_fallback(
        "onyx.auth.users", "get_default_admin_user_emails_", lambda: list[str]()
    )
    return get_default_admin_user_emails_fn()


def get_total_users_count(db_session: Session) -> int:
    """
    Returns the total number of users in the system.
    This is the sum of users and invited users.
    """
    user_count = (
        db_session.query(User)
        .filter(
            ~User.email.endswith(get_api_key_email_pattern()),  # type: ignore
            User.role != UserRole.EXT_PERM_USER,
        )
        .count()
    )
    invited_users = len(get_invited_users())
    return user_count + invited_users


async def get_user_count(only_admin_users: bool = False) -> int:
    async with get_async_session_with_tenant() as session:
        stmt = select(func.count(User.id))
        if only_admin_users:
            stmt = stmt.where(User.role == UserRole.ADMIN)
        result = await session.execute(stmt)
        user_count = result.scalar()
        if user_count is None:
            raise RuntimeError("Was not able to fetch the user count.")
        return user_count


# Need to override this because FastAPI Users doesn't give flexibility for backend field creation logic in OAuth flow
class SQLAlchemyUserAdminDB(SQLAlchemyUserDatabase[UP, ID]):
    async def create(
        self,
        create_dict: Dict[str, Any],
    ) -> UP:
        user_count = await get_user_count()
        if user_count == 0 or create_dict["email"] in get_default_admin_user_emails():
            create_dict["role"] = UserRole.ADMIN
        else:
            create_dict["role"] = UserRole.BASIC
        return await super().create(create_dict)


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserAdminDB, None]:
    yield SQLAlchemyUserAdminDB(session, User, OAuthAccount)  # type: ignore


async def get_access_token_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyAccessTokenDatabase, None]:
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)  # type: ignore
