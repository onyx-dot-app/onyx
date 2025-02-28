import contextlib
from collections.abc import AsyncGenerator
from collections.abc import Generator
from contextlib import asynccontextmanager
from contextlib import contextmanager
from typing import ContextManager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.configs.app_configs import POSTGRES_IDLE_SESSIONS_TIMEOUT
from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.session_schema_translate_map import (
    OnyxSchemaTranslateMapSession as OnyxSession,
)
from onyx.db.utils import is_valid_schema_name
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()

SessionFactory: sessionmaker[Session] | None = None


@contextmanager
def get_session_with_current_tenant() -> Generator[Session, None, None]:
    tenant_id = get_current_tenant_id()

    with OnyxSession.get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


# Used in multi tenant mode when need to refer to the shared `public` schema
@contextmanager
def get_session_with_shared_schema() -> Generator[Session, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    with OnyxSession.get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA
    ) as session:
        yield session
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def get_session_generator_with_tenant() -> Generator[Session, None, None]:
    tenant_id = get_current_tenant_id()
    with OnyxSession.get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


def get_session_context_manager() -> ContextManager[Session]:
    """Context manager for database sessions."""
    return contextlib.contextmanager(get_session_generator_with_tenant)()


def get_session_factory() -> sessionmaker[Session]:
    global SessionFactory
    if SessionFactory is None:
        SessionFactory = sessionmaker(bind=get_sqlalchemy_engine())
    return SessionFactory


@contextmanager
def get_session_with_tenant(*, tenant_id: str | None) -> Generator[Session, None, None]:
    with OnyxSession.get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


def get_session() -> Generator[Session, None, None]:
    yield from OnyxSession.get_session()


def get_multi_tenant_session(tenant_id: str) -> Generator[Session, None, None]:
    yield from OnyxSession.get_multi_tenant_session(tenant_id)


def get_single_tenant_session() -> Generator[Session, None, None]:
    yield from OnyxSession.get_single_tenant_session()


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Proxy method that simply delegates to `get_async_session`."""
    async for session in OnyxSession.get_async_session():
        yield session


@asynccontextmanager
async def get_async_session_with_tenant(
    tenant_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    if tenant_id is None:
        tenant_id = get_current_tenant_id()

    if not is_valid_schema_name(tenant_id):
        logger.error(f"Invalid tenant ID: {tenant_id}")
        raise ValueError("Invalid tenant ID")

    async for session in OnyxSession.get_multi_tenant_async_session(tenant_id):
        if POSTGRES_IDLE_SESSIONS_TIMEOUT:
            await session.execute(
                text(
                    f"SET idle_in_transaction_session_timeout = {POSTGRES_IDLE_SESSIONS_TIMEOUT}"
                )
            )

        yield session
