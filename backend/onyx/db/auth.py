from collections.abc import AsyncGenerator
from collections.abc import Callable
from typing import Any
from typing import Dict
from typing import TypeVar

from fastapi import Depends
from fastapi_users.models import ID
from fastapi_users.models import UP
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy import func
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.db.api_key import get_api_key_email_pattern
from onyx.db.engine.async_sql_engine import get_async_session
from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.models import AccessToken
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation_with_fallback,
)

T = TypeVar("T", bound=tuple[Any, ...])


def get_default_admin_user_emails() -> list[str]:
    """Returns a list of emails who should default to Admin role.
    Only used in the EE version. For MIT, just return empty list."""
    get_default_admin_user_emails_fn: Callable[[], list[str]] = (
        fetch_versioned_implementation_with_fallback(
            "onyx.auth.users", "get_default_admin_user_emails_", lambda: list[str]()
        )
    )
    return get_default_admin_user_emails_fn()


def _add_live_user_count_where_clause(
    select_stmt: Select[T],
    only_admin_users: bool,
) -> Select[T]:
    """
    Builds a SQL column expression that can be used to filter out
    users who should not be included in the live user count.
    """
    select_stmt = select_stmt.where(~User.email.endswith(get_api_key_email_pattern()))  # type: ignore
    if only_admin_users:
        return select_stmt.where(User.role == UserRole.ADMIN)

    return select_stmt.where(
        User.role != UserRole.EXT_PERM_USER,
    )


def get_live_users_count(db_session: Session) -> int:
    """
    Returns the number of users in the system.
    This does NOT include invited users, "users" pulled in
    from external connectors, or API keys.
    """
    count_stmt = func.count(User.id)  # type: ignore
    select_stmt = select(count_stmt)
    select_stmt_w_filters = _add_live_user_count_where_clause(select_stmt, False)
    user_count = db_session.scalar(select_stmt_w_filters)
    if user_count is None:
        raise RuntimeError("Was not able to fetch the user count.")
    return user_count


async def get_user_count(only_admin_users: bool = False) -> int:
    async with get_async_session_context_manager() as session:
        count_stmt = func.count(User.id)  # type: ignore
        stmt = select(count_stmt)
        stmt_w_filters = _add_live_user_count_where_clause(stmt, only_admin_users)
        user_count = await session.scalar(stmt_w_filters)
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
