import threading
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
    POSTGRES_POOL_PRE_PING,
    POSTGRES_POOL_RECYCLE,
    POSTGRES_USE_NULL_POOL,
)
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.db.engine.pg_ssl import create_pg_ssl_context
from onyx.db.engine.shard_registry import (
    ShardSpec,
    get_default_shard_name,
    get_shard_spec,
    is_default_shard,
    shard_pool_divisor,
)
from onyx.db.engine.shard_routing import get_shard_for_tenant
from onyx.db.engine.sql_engine import (
    ASYNC_DB_API,
    USE_IAM_AUTH,
    SqlEngine,
    build_connection_string,
    is_valid_schema_name,
)
from shared_configs.configs import MULTI_TENANT, POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import get_current_tenant_id

# One async engine per shard, created lazily. With no sharding configured this holds
# exactly one entry and behaves as the previous process-global singleton did.
_ASYNC_ENGINES: dict[str, AsyncEngine] = {}
_ASYNC_ENGINES_LOCK = threading.Lock()


def _build_async_engine(spec: ShardSpec) -> AsyncEngine:
    app_name = SqlEngine.get_app_name() + "_async"
    if not is_default_shard(spec.name):
        app_name = f"{app_name}_{spec.name}"

    connection_string = build_connection_string(
        db_api=ASYNC_DB_API,
        user=spec.user,
        password=spec.password,
        host=spec.host,
        port=spec.port,
        db=spec.db,
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
        # Divide rather than multiply the budget across shards, matching the sync
        # engine. With one shard the divisor is 1, i.e. sizing is unchanged.
        divisor = shard_pool_divisor()
        engine_kwargs["pool_size"] = max(1, POSTGRES_API_SERVER_POOL_SIZE // divisor)
        engine_kwargs["max_overflow"] = (
            0
            if POSTGRES_API_SERVER_POOL_OVERFLOW == 0
            else max(1, POSTGRES_API_SERVER_POOL_OVERFLOW // divisor)
        )

    engine = create_async_engine(connection_string, **engine_kwargs)

    if USE_IAM_AUTH:
        # Bound to this shard's coordinates: an RDS IAM token is only valid for the
        # host/port/user it was minted for, so the global POSTGRES_* values would be
        # rejected for a shard on a different instance.
        iam_host = spec.host
        iam_port = spec.port
        iam_user = spec.user

        @event.listens_for(engine.sync_engine, "do_connect")
        def provide_iam_token_async(
            dialect: Any,  # noqa: ARG001
            conn_rec: Any,  # noqa: ARG001
            cargs: Any,  # noqa: ARG001
            cparams: Any,
        ) -> None:
            # For async engine using asyncpg, we still need to set the IAM token here.
            token = get_iam_auth_token(iam_host, iam_port, iam_user, AWS_REGION_NAME)
            cparams["password"] = token
            cparams["ssl"] = create_pg_ssl_context()

    return engine


def get_async_engine_for_shard(shard_name: str) -> AsyncEngine:
    engine = _ASYNC_ENGINES.get(shard_name)
    if engine is not None:
        return engine

    with _ASYNC_ENGINES_LOCK:
        # Re-check: another coroutine may have built it while we waited.
        engine = _ASYNC_ENGINES.get(shard_name)
        if engine is not None:
            return engine

        engine = _build_async_engine(get_shard_spec(shard_name))
        _ASYNC_ENGINES[shard_name] = engine
        return engine


def get_async_engine_for_tenant(tenant_id: str) -> AsyncEngine:
    """Async engine for the database holding this tenant's schema."""
    return get_async_engine_for_shard(get_shard_for_tenant(tenant_id))


def get_sqlalchemy_async_engine() -> AsyncEngine:
    """Async engine for the default shard.

    Kept for callers that are not tenant-scoped. Anything that touches per-tenant
    data must go through `get_async_engine_for_tenant`, or it will read and write
    the default database regardless of where the tenant actually lives.
    """
    return get_async_engine_for_shard(get_default_shard_name())


async def reset_sqlalchemy_async_engine() -> None:
    """Dispose every per-shard async engine and drop the references so a
    subsequent ``get_sqlalchemy_async_engine()`` rebuilds them from scratch.

    Must be awaited so asyncpg's pool can close its connections (rather than
    leaking them when the worker exits — uvicorn ``--reload`` exercises this
    path on every file change).
    """
    global _ASYNC_ENGINES
    with _ASYNC_ENGINES_LOCK:
        engines = list(_ASYNC_ENGINES.values())
        _ASYNC_ENGINES = {}
    for engine in engines:
        await engine.dispose()


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

    # Routes to the tenant's shard, not just its schema. With one shard configured
    # this is the same engine the process has always used.
    engine = get_async_engine_for_tenant(tenant_id)

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
