from collections.abc import AsyncGenerator
from typing import Optional

from fastapi import Depends
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.orm import relationship

from onyx.db.engine import get_async_session

Base: DeclarativeMeta = declarative_base()


class EssentialUser(SQLAlchemyBaseUserTableUUID, Base):
    """
    A simplified user model that only includes essential columns needed for authentication.
    This is used during the initial tenant setup phase to avoid errors with missing columns
    that would be added in later migrations.
    """

    __tablename__ = "user"

    email: str = Column(String(length=320), unique=True, index=True, nullable=False)
    hashed_password: Optional[str] = Column(String(length=1024), nullable=True)
    is_active: bool = Column(Boolean, default=True, nullable=False)
    is_superuser: bool = Column(Boolean, default=False, nullable=False)
    is_verified: bool = Column(Boolean, default=False, nullable=False)

    # Relationships are defined but not used in the essential auth flow
    oauth_accounts = relationship("OAuthAccount", lazy="joined")
    credentials = relationship("Credential", lazy="joined")


async def get_essential_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    """
    Get a user database that uses the essential user model.
    This avoids errors with missing columns during the initial tenant setup.
    """
    yield SQLAlchemyUserDatabase(session, EssentialUser)
