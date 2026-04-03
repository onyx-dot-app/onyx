from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from typing import AsyncContextManager

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_POOL_PRE_PING
from onyx.configs.app_configs import POSTGRES_POOL_RECYCLE
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_REQUIRE_SSL
from onyx.configs.app_configs import POSTGRES_USE_NULL_POOL
from onyx.configs.app_configs import POSTGRES_USER
from onyx.db.engine.iam_auth import get_iam_auth_token
from onyx.db.engine.rds_ssl import get_rds_ssl_context_or_require
from onyx.db.engine.sql_engine import ASYNC_DB_API
from onyx.db.engine.sql_engine import build_connection_string
from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.engine.sql_engine import USE_IAM_AUTH
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

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

        # Configure SSL if required
        # IAM auth always requires SSL, or can be explicitly enabled via POSTGRES_REQUIRE_SSL
        if USE_IAM_AUTH or POSTGRES_REQUIRE_SSL:
            ssl_context = get_rds_ssl_context_or_require()
            connect_args["ssl"] = ssl_context

        engine_kwargs = {
            "connect_args": connect_args,
            "pool_pre_ping": POSTGRES_POOL_PRE_PING,
            "pool_recycle": POSTGRES_POOL_RECYCLE,
        }

        if POSTGRES_USE_NULL_POOL:
            engine_kwargs["poolclass"] = pool.NullPool
        else:
            engine_kwargs["pool_size"] = POSTGRES_API_SERVER_POOL_SIZE
            engine_kwargs["max_overflow"] = POSTGRES_API_SERVER_POOL_OVERFLOW

        _ASYNC_ENGINE = create_async_engine(
            connection_string,
            **engine_kwargs,
        )

        # For IAM auth, set up event listener to generate fresh tokens
        # IAM auth requires SSL, so ssl_context will always be defined here
        if USE_IAM_AUTH:

            @event.listens_for(_ASYNC_ENGINE.sync_engine, "do_connect")
            def provide_iam_token_async(
                dialect: Any,  # noqa: ARG001
                conn_rec: Any,  # noqa: ARG001
                cargs: Any,  # noqa: ARG001
                cparams: Any,
            ) -> None:
                try:
                    token = get_iam_auth_token(
                        POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER, AWS_REGION_NAME
                    )
                    if not token:
                        raise RuntimeError("IAM token is None after generation")

                    cparams["password"] = token

                    # Ensure SSL is configured (required for IAM auth)
                    if "ssl" not in cparams or cparams["ssl"] is None:
                        cparams["ssl"] = get_rds_ssl_context_or_require()

                except Exception as e:
                    logger.error(f"Failed to configure IAM auth: {e}")
                    raise

    return _ASYNC_ENGINE


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
