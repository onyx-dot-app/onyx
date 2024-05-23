from collections.abc import AsyncGenerator
from typing import Any
from typing import Dict

from fastapi import Depends
from fastapi_users.models import UP
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from danswer.auth.schemas import UserRole
from danswer.db.engine import get_async_session
from danswer.db.engine import get_sqlalchemy_async_engine
from danswer.db.models import AccessToken
from danswer.db.models import OAuthAccount
from danswer.db.models import User


async def get_user_count() -> int:
    async with AsyncSession(get_sqlalchemy_async_engine()) as asession:
        stmt = select(func.count(User.id))
        result = await asession.execute(stmt)
        user_count = result.scalar()
        if user_count is None:
            raise RuntimeError("Was not able to fetch the user count.")
        return user_count


# Need to override this because FastAPI Users doesn't give flexibility for backend field creation logic in OAuth flow
class SQLAlchemyUserAdminDB(SQLAlchemyUserDatabase):
    async def create(self, create_dict: Dict[str, Any]) -> UP:
        user_count = await get_user_count()
        if user_count == 0:
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
