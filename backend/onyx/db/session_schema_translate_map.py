"""
Implements multi-tenant / schema handling for a session via
SQLAlchemy's schema_translate_map feature.

This is better for us than
SET search_path because that approach pins the connection in RDS proxy since it
alters the connection state.
"""
from collections.abc import AsyncGenerator
from collections.abc import Generator
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from onyx.configs.app_configs import POSTGRES_IDLE_SESSIONS_TIMEOUT
from onyx.db.engine import get_sqlalchemy_async_engine
from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.utils import is_valid_schema_name
from onyx.server.utils import BasicAuthenticationError
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id


class OnyxSchemaTranslateMapSession:
    @contextmanager
    @staticmethod
    def get_session_with_tenant(
        *, tenant_id: str | None
    ) -> Generator[Session, None, None]:
        """
        Generate a database session for a specific tenant.
        """
        if tenant_id is None:
            tenant_id = POSTGRES_DEFAULT_SCHEMA

        schema_translate_map = {None: tenant_id}

        engine = get_sqlalchemy_engine()

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        with engine.connect().execution_options(
            schema_translate_map=schema_translate_map
        ) as connection:
            dbapi_connection = connection.connection
            if POSTGRES_IDLE_SESSIONS_TIMEOUT:
                try:
                    cursor = dbapi_connection.cursor()
                    cursor.execute(
                        text(
                            f"SET SESSION idle_in_transaction_session_timeout = {POSTGRES_IDLE_SESSIONS_TIMEOUT}"
                        )
                    )
                finally:
                    cursor.close()

            with Session(bind=connection, expire_on_commit=False) as session:
                yield session

    @staticmethod
    def get_session() -> Generator[Session, None, None]:
        if MULTI_TENANT:
            tenant_id = get_current_tenant_id()
            yield from OnyxSchemaTranslateMapSession.get_multi_tenant_session(tenant_id)
            return

        yield from OnyxSchemaTranslateMapSession.get_single_tenant_session()
        return

    @staticmethod
    def get_multi_tenant_session(tenant_id: str) -> Generator[Session, None, None]:
        schema_translate_map = {None: tenant_id}

        if tenant_id == POSTGRES_DEFAULT_SCHEMA and MULTI_TENANT:
            raise BasicAuthenticationError(detail="User must authenticate")

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        engine = get_sqlalchemy_engine()
        with engine.connect().execution_options(
            schema_translate_map=schema_translate_map
        ) as connection:
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session

    @staticmethod
    def get_single_tenant_session() -> Generator[Session, None, None]:
        engine = get_sqlalchemy_engine()

        # single tenant
        with engine.connect() as connection:
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session

    @staticmethod
    async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
        if MULTI_TENANT:
            tenant_id = get_current_tenant_id()
            async for session in OnyxSchemaTranslateMapSession.get_multi_tenant_async_session(
                tenant_id
            ):
                yield session
            return

        async for session in OnyxSchemaTranslateMapSession.get_single_tenant_async_session():
            yield session

    @staticmethod
    async def get_multi_tenant_async_session(
        tenant_id: str,
    ) -> AsyncGenerator[AsyncSession, None]:
        engine = get_sqlalchemy_async_engine()

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        # Create connection with schema translation
        schema_translate_map = {None: tenant_id}
        async with engine.connect() as connection:
            connection = await connection.execution_options(
                schema_translate_map=schema_translate_map
            )
            async with AsyncSession(
                bind=connection, expire_on_commit=False
            ) as async_session:
                yield async_session

    @staticmethod
    async def get_single_tenant_async_session() -> AsyncGenerator[AsyncSession, None]:
        engine = get_sqlalchemy_async_engine()

        # single tenant
        async with AsyncSession(engine, expire_on_commit=False) as async_session:
            yield async_session
