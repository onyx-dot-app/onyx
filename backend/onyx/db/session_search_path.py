"""
Implements multi-tenant / schema handling for a session via "SET search_path".

This is worse for us than schema_translate_map because this approach pins the connection
 in RDS proxy since it alters the connection state.

Keeping this approach here while we test/iterate.
"""
from collections.abc import AsyncGenerator
from collections.abc import Generator
from contextlib import asynccontextmanager
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.configs.app_configs import POSTGRES_IDLE_SESSIONS_TIMEOUT
from onyx.db.engine import get_sqlalchemy_async_engine
from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.utils import is_valid_schema_name
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id


logger = setup_logger()


AsyncSessionLocal = sessionmaker(  # type: ignore
    bind=get_sqlalchemy_async_engine(),
    class_=AsyncSession,
    expire_on_commit=False,
)


class OnyxSearchPathSession:
    @staticmethod
    def _set_search_path_on_checkout(
        dbapi_conn: Any, connection_record: Any, connection_proxy: Any
    ) -> None:
        tenant_id = get_current_tenant_id()
        if tenant_id and is_valid_schema_name(tenant_id):
            with dbapi_conn.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{tenant_id}"')

    @contextmanager
    @staticmethod
    def get_session_with_tenant(*, tenant_id: str) -> Generator[Session, None, None]:
        """
        Generate a database session for a specific tenant.
        """
        if tenant_id is None:
            tenant_id = POSTGRES_DEFAULT_SCHEMA

        engine = get_sqlalchemy_engine()

        event.listen(
            engine, "checkout", OnyxSearchPathSession._set_search_path_on_checkout
        )

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        with engine.connect() as connection:
            dbapi_connection = connection.connection
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute(f'SET search_path = "{tenant_id}"')
                if POSTGRES_IDLE_SESSIONS_TIMEOUT:
                    cursor.execute(
                        text(
                            f"SET SESSION idle_in_transaction_session_timeout = {POSTGRES_IDLE_SESSIONS_TIMEOUT}"
                        )
                    )
            finally:
                cursor.close()

            with Session(bind=connection, expire_on_commit=False) as session:
                try:
                    yield session
                finally:
                    if MULTI_TENANT:
                        cursor = dbapi_connection.cursor()
                        try:
                            cursor.execute('SET search_path TO "$user", public')
                        finally:
                            cursor.close()

    @staticmethod
    def get_session() -> Generator[Session, None, None]:
        if MULTI_TENANT:
            tenant_id = get_current_tenant_id()
            yield from OnyxSearchPathSession.get_multi_tenant_session(tenant_id)
            return

        yield from OnyxSearchPathSession.get_single_tenant_session()
        return

    @staticmethod
    def get_multi_tenant_session(tenant_id: str) -> Generator[Session, None, None]:
        if tenant_id == POSTGRES_DEFAULT_SCHEMA and MULTI_TENANT:
            raise BasicAuthenticationError(detail="User must authenticate")

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        engine = get_sqlalchemy_engine()
        with Session(engine, expire_on_commit=False) as session:
            session.execute(text(f'SET search_path = "{tenant_id}"'))
            yield session

    @staticmethod
    def get_single_tenant_session() -> Generator[Session, None, None]:
        engine = get_sqlalchemy_engine()

        with Session(engine, expire_on_commit=False) as session:
            yield session

    @staticmethod
    async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
        if MULTI_TENANT:
            tenant_id = get_current_tenant_id()
            async for session in OnyxSearchPathSession.get_multi_tenant_async_session(
                tenant_id
            ):
                yield session
            return

        async for session in OnyxSearchPathSession.get_single_tenant_async_session():
            yield session

    @staticmethod
    async def get_multi_tenant_async_session(
        tenant_id: str,
    ) -> AsyncGenerator[AsyncSession, None]:
        engine = get_sqlalchemy_async_engine()

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        async with AsyncSession(engine, expire_on_commit=False) as async_session:
            await async_session.execute(text(f'SET search_path = "{tenant_id}"'))
            yield async_session

    @staticmethod
    async def get_single_tenant_async_session() -> AsyncGenerator[AsyncSession, None]:
        engine = get_sqlalchemy_async_engine()

        # single tenant
        async with AsyncSession(engine, expire_on_commit=False) as async_session:
            yield async_session

    @asynccontextmanager
    @staticmethod
    async def get_async_session_with_tenant(
        tenant_id: str | None = None,
    ) -> AsyncGenerator[AsyncSession, None]:
        if tenant_id is None:
            tenant_id = get_current_tenant_id()

        if not is_valid_schema_name(tenant_id):
            logger.error(f"Invalid tenant ID: {tenant_id}")
            raise ValueError("Invalid tenant ID")

        async with AsyncSessionLocal() as session:
            session.sync_session.info["tenant_id"] = tenant_id

            if POSTGRES_IDLE_SESSIONS_TIMEOUT:
                await session.execute(
                    text(
                        f"SET idle_in_transaction_session_timeout = {POSTGRES_IDLE_SESSIONS_TIMEOUT}"
                    )
                )

            try:
                yield session
            finally:
                pass
