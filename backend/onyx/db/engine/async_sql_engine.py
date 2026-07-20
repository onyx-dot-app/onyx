from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, AsyncContextManager

from fastapi import HTTPException
from sqlalchemy import event, pool
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from onyx.configs.app_configs import (
    AWS_REGION_NAME,
    POSTGRES_API_SERVER_POOL_OVERFLOW,
    POSTGRES_API_SERVER_POOL_SIZE,
    POSTGRES_HOST,
    POSTGRES_POOL_PRE_PING,
    POSTGRES_POOL_RECYCLE,
    POSTGRES_PORT,
    POSTGRES_USE_NULL_POOL,
    POSTGRES_USER,
)
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.db.engine.pg_ssl import create_pg_ssl_context
from onyx.db.engine.sql_engine import (
    ASYNC_DB_API,
    USE_IAM_AUTH,
    SqlEngine,
    build_connection_string,
    is_valid_schema_name,
)
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import get_current_tenant_id

# Global so we don't create more than one engine per process
_ASYNC_ENGINE: AsyncEngine | None = None


def get_sqlalchemy_async_engine() -> AsyncEngine:
    global _ASYNC_ENGINE
    if _ASYNC_ENGINE is None:
        app_name = SqlEngine.get_app_name() + "_async"
        connection_string = build_connection_string(
            db_api=ASYNC_DB_API,
            use_iam_auth=USE_IAM_AUTH,
        )

        connect_args: dict[str, Any] = {}
        if app_name:
            connect_args["server_settings"] = {"application_name": app_name}

        connect_args["ssl"] = create_pg_ssl_context()

        # Disable asyncpg's named prepared-statement cache. Cache-vs-server
        # desync produces intermittent `MissingGreenlet` /
        # `prepared statement does not exist` errors under poolers and on
        # cold async connects.
        connect_args["statement_cache_size"] = 0

        engine_kwargs = {
            "connect_args": connect_args,
            "pool_pre_ping": POSTGRES_POOL_PRE_PING,
            "pool_recycle": POSTGRES_POOL_RECYCLE,
        }

        if POSTGRES_USE_NULL_POOL:
            engine_kwargs["poolclass"] = pool.NullPool  # ty: ignore[invalid-assignment]
        else:
            engine_kwargs["pool_size"] = POSTGRES_API_SERVER_POOL_SIZE
            engine_kwargs["max_overflow"] = POSTGRES_API_SERVER_POOL_OVERFLOW

        _ASYNC_ENGINE = create_async_engine(
            connection_string,
            **engine_kwargs,
        )

        if USE_IAM_AUTH:

            @event.listens_for(_ASYNC_ENGINE.sync_engine, "do_connect")
            def provide_iam_token_async(
                dialect: Any,  # noqa: ARG001
                conn_rec: Any,  # noqa: ARG001
                cargs: Any,  # noqa: ARG001
                cparams: Any,
            ) -> None:
                # For async engine using asyncpg, we still need to set the IAM token here.
                host = POSTGRES_HOST
                port = POSTGRES_PORT
                user = POSTGRES_USER
                token = get_iam_auth_token(host, port, user, AWS_REGION_NAME)
                cparams["password"] = token
                cparams["ssl"] = create_pg_ssl_context()

    return _ASYNC_ENGINE


async def reset_sqlalchemy_async_engine() -> None:
    """Dispose the process-global async engine and drop the reference so a
    subsequent ``get_sqlalchemy_async_engine()`` rebuilds it from scratch.

    Must be awaited so asyncpg's pool can close its connections (rather than
    leaking them when the worker exits — uvicorn ``--reload`` exercises this
    path on every file change).
    """
    global _ASYNC_ENGINE
    if _ASYNC_ENGINE is not None:
        await _ASYNC_ENGINE.dispose()
        _ASYNC_ENGINE = None


async def get_async_session(
    tenant_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """For use w/ Depends for *async* FastAPI endpoints.

    For standard `async with ... as ...` use, use get_async_session_context_manager.
    """

    if tenant_id is None:
        tenant_id = get_current_tenant_id()

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    engine = get_sqlalchemy_async_engine()

    # no need to use the schema translation map for self-hosted + default schema
    if not MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session
        return

    # Create connection with schema translation to handle querying the right schema
    schema_translate_map = {None: tenant_id}
    async with engine.connect() as connection:
        connection = await connection.execution_options(
            schema_translate_map=schema_translate_map
        )
        async with AsyncSession(
            bind=connection, expire_on_commit=False
        ) as async_session:
            yield async_session


def get_async_session_context_manager(
    tenant_id: str | None = None,
) -> AsyncContextManager[AsyncSession]:
    return asynccontextmanager(get_async_session)(tenant_id)
