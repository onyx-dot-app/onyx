import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from typing import AsyncContextManager

import asyncpg  # type: ignore
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.app_configs import POSTGRES_DB
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_HOSTS
from onyx.configs.app_configs import POSTGRES_POOL_PRE_PING
from onyx.configs.app_configs import POSTGRES_POOL_RECYCLE
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USE_NULL_POOL
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.iam_auth import create_ssl_context_if_iam
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.db.engine.sql_engine import ASYNC_DB_API
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.sql_engine import USE_IAM_AUTH
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import get_current_tenant_id


_ASYNC_ENGINES: dict[int, AsyncEngine] = {}
_ASYNC_ENGINE_LOCK = threading.Lock()


async def get_async_connection() -> Any:
    """Custom connection function for async engine when using IAM auth."""
    host = POSTGRES_HOST
    port = POSTGRES_PORT
    user = POSTGRES_USER
    db = POSTGRES_DB
    token = get_iam_auth_token(host, port, user, AWS_REGION_NAME)

    return await asyncpg.connect(
        user=user, password=token, host=host, port=int(port), database=db, ssl="require"
    )


def _create_async_engine_for_host(
    host: str,
    pool_size: int = POSTGRES_API_SERVER_POOL_SIZE,
    max_overflow: int = POSTGRES_API_SERVER_POOL_OVERFLOW,
) -> AsyncEngine:
    app_name = SqlEngine.get_app_name() + "_async"
    connection_string = build_connection_string(
        db_api=ASYNC_DB_API,
        host=host,
        use_iam_auth=USE_IAM_AUTH,
    )

    connect_args: dict[str, Any] = {}
    if app_name:
        connect_args["server_settings"] = {"application_name": app_name}
    connect_args["ssl"] = create_ssl_context_if_iam()

    engine_kwargs: dict[str, Any] = {
        "connect_args": connect_args,
        "pool_pre_ping": POSTGRES_POOL_PRE_PING,
        "pool_recycle": POSTGRES_POOL_RECYCLE,
    }

    if POSTGRES_USE_NULL_POOL:
        engine_kwargs["poolclass"] = pool.NullPool
    else:
        engine_kwargs["pool_size"] = pool_size
        engine_kwargs["max_overflow"] = max_overflow

    engine = create_async_engine(connection_string, **engine_kwargs)

    if USE_IAM_AUTH:

        @event.listens_for(engine.sync_engine, "do_connect")
        def provide_iam_token_async(
            dialect: Any,  # noqa: ARG001
            conn_rec: Any,  # noqa: ARG001
            cargs: Any,  # noqa: ARG001
            cparams: Any,
        ) -> None:
            h = host
            token = get_iam_auth_token(h, POSTGRES_PORT, POSTGRES_USER, AWS_REGION_NAME)
            cparams["password"] = token
            cparams["ssl"] = create_ssl_context_if_iam()

    return engine


def get_sqlalchemy_async_engine(host_index: int = 0) -> AsyncEngine:
    engine = _ASYNC_ENGINES.get(host_index)
    if engine is not None:
        return engine

    with _ASYNC_ENGINE_LOCK:
        engine = _ASYNC_ENGINES.get(host_index)
        if engine is not None:
            return engine

        host = (
            POSTGRES_HOSTS[host_index]
            if host_index < len(POSTGRES_HOSTS)
            else POSTGRES_HOST
        )
        num_hosts = max(1, len(POSTGRES_HOSTS))
        per_host_pool = max(1, POSTGRES_API_SERVER_POOL_SIZE // num_hosts)
        per_host_overflow = max(0, POSTGRES_API_SERVER_POOL_OVERFLOW // num_hosts)

        engine = _create_async_engine_for_host(
            host, pool_size=per_host_pool, max_overflow=per_host_overflow
        )
        _ASYNC_ENGINES[host_index] = engine
        return engine


def _get_host_index_for_tenant(tenant_id: str) -> int:
    from onyx.db.engine.tenant_host_mapping import get_host_index_for_tenant

    return get_host_index_for_tenant(tenant_id)


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

    host_index = _get_host_index_for_tenant(tenant_id)
    engine = get_sqlalchemy_async_engine(host_index)

    if not MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
        async with AsyncSession(bind=engine, expire_on_commit=False) as session:
            yield session
        return

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
