import contextlib
import os
import re
import ssl
import threading
import time
from collections.abc import AsyncGenerator
from collections.abc import Generator
from contextlib import asynccontextmanager
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from typing import AsyncContextManager

import asyncpg  # type: ignore
import boto3
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy import text
from sqlalchemy.engine import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from onyx.configs.app_configs import AWS_REGION_NAME
from onyx.configs.app_configs import LOG_POSTGRES_CONN_COUNTS
from onyx.configs.app_configs import LOG_POSTGRES_LATENCY
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from onyx.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from onyx.configs.app_configs import POSTGRES_DB
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_IDLE_SESSIONS_TIMEOUT
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_POOL_PRE_PING
from onyx.configs.app_configs import POSTGRES_POOL_RECYCLE
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USE_NULL_POOL
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.constants import POSTGRES_UNKNOWN_APP_NAME
from onyx.configs.constants import SSL_CERT_FILE
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.configs import TENANT_ID_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

SYNC_DB_API = "psycopg2"
ASYNC_DB_API = "asyncpg"

# why isn't this in configs?
USE_IAM_AUTH = os.getenv("USE_IAM_AUTH", "False").lower() == "true"

SCHEMA_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


# Global so we don't create more than one engine per process
_ASYNC_ENGINE: AsyncEngine | None = None
SessionFactory: sessionmaker[Session] | None = None


def create_ssl_context_if_iam() -> ssl.SSLContext | None:
    """Create an SSL context if IAM authentication is enabled, else return None."""
    if USE_IAM_AUTH:
        return ssl.create_default_context(cafile=SSL_CERT_FILE)
    return None


ssl_context = create_ssl_context_if_iam()


def get_iam_auth_token(
    host: str, port: str, user: str, region: str = "us-east-2"
) -> str:
    """
    Generate an IAM authentication token using boto3.
    """
    client = boto3.client("rds", region_name=region)
    token = client.generate_db_auth_token(
        DBHostname=host, Port=int(port), DBUsername=user
    )
    return token


def configure_psycopg2_iam_auth(
    cparams: dict[str, Any], host: str, port: str, user: str, region: str
) -> None:
    """
    Configure cparams for psycopg2 with IAM token and SSL.
    """
    token = get_iam_auth_token(host, port, user, region)
    cparams["password"] = token
    cparams["sslmode"] = "require"
    cparams["sslrootcert"] = SSL_CERT_FILE


def build_connection_string(
    *,
    db_api: str = ASYNC_DB_API,
    user: str = POSTGRES_USER,
    password: str = POSTGRES_PASSWORD,
    host: str = POSTGRES_HOST,
    port: str = POSTGRES_PORT,
    db: str = POSTGRES_DB,
    app_name: str | None = None,
    use_iam_auth: bool = USE_IAM_AUTH,
    region: str = "us-west-2",
) -> str:
    if use_iam_auth:
        base_conn_str = f"postgresql+{db_api}://{user}@{host}:{port}/{db}"
    else:
        base_conn_str = f"postgresql+{db_api}://{user}:{password}@{host}:{port}/{db}"

    # For asyncpg, do not include application_name in the connection string
    if app_name and db_api != "asyncpg":
        if "?" in base_conn_str:
            return f"{base_conn_str}&application_name={app_name}"
        else:
            return f"{base_conn_str}?application_name={app_name}"
    return base_conn_str


if LOG_POSTGRES_LATENCY:

    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(  # type: ignore
        conn, cursor, statement, parameters, context, executemany
    ):
        conn.info["query_start_time"] = time.time()

    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(  # type: ignore
        conn, cursor, statement, parameters, context, executemany
    ):
        total_time = time.time() - conn.info["query_start_time"]
        if total_time > 0.1:
            logger.debug(
                f"Query Complete: {statement}\n\nTotal Time: {total_time:.4f} seconds"
            )


if LOG_POSTGRES_CONN_COUNTS:
    checkout_count = 0
    checkin_count = 0

    @event.listens_for(Engine, "checkout")
    def log_checkout(dbapi_connection, connection_record, connection_proxy):  # type: ignore
        global checkout_count
        checkout_count += 1

        active_connections = connection_proxy._pool.checkedout()
        idle_connections = connection_proxy._pool.checkedin()
        pool_size = connection_proxy._pool.size()
        logger.debug(
            "Connection Checkout\n"
            f"Active Connections: {active_connections};\n"
            f"Idle: {idle_connections};\n"
            f"Pool Size: {pool_size};\n"
            f"Total connection checkouts: {checkout_count}"
        )

    @event.listens_for(Engine, "checkin")
    def log_checkin(dbapi_connection, connection_record):  # type: ignore
        global checkin_count
        checkin_count += 1
        logger.debug(f"Total connection checkins: {checkin_count}")


def get_db_current_time(db_session: Session) -> datetime:
    result = db_session.execute(text("SELECT NOW()")).scalar()
    if result is None:
        raise ValueError("Database did not return a time")
    return result


def is_valid_schema_name(name: str) -> bool:
    return SCHEMA_NAME_REGEX.match(name) is not None


class SqlEngine:
    _engine: Engine | None = None
    _lock: threading.Lock = threading.Lock()
    _app_name: str = POSTGRES_UNKNOWN_APP_NAME

    @classmethod
    def init_engine(
        cls,
        pool_size: int,
        # is really `pool_max_overflow`, but calling it `max_overflow` to stay consistent with SQLAlchemy
        max_overflow: int,
        app_name: str | None = None,
        db_api: str = SYNC_DB_API,
        use_iam: bool = USE_IAM_AUTH,
        connection_string: str | None = None,
        **extra_engine_kwargs: Any,
    ) -> None:
        """NOTE: enforce that pool_size and pool_max_overflow are passed in. These are
        important args, and if incorrectly specified, we have run into hitting the pool
        limit / using too many connections and overwhelming the database.

        Specifying connection_string directly will cause some of the other parameters
        to be ignored.
        """
        with cls._lock:
            if cls._engine:
                return

            if not connection_string:
                connection_string = build_connection_string(
                    db_api=db_api,
                    app_name=cls._app_name + "_sync",
                    use_iam_auth=use_iam,
                )

            # Start with base kwargs that are valid for all pool types
            final_engine_kwargs: dict[str, Any] = {}

            if POSTGRES_USE_NULL_POOL:
                # if null pool is specified, then we need to make sure that
                # we remove any passed in kwargs related to pool size that would
                # cause the initialization to fail
                final_engine_kwargs.update(extra_engine_kwargs)

                final_engine_kwargs["poolclass"] = pool.NullPool
                if "pool_size" in final_engine_kwargs:
                    del final_engine_kwargs["pool_size"]
                if "max_overflow" in final_engine_kwargs:
                    del final_engine_kwargs["max_overflow"]
            else:
                final_engine_kwargs["pool_size"] = pool_size
                final_engine_kwargs["max_overflow"] = max_overflow
                final_engine_kwargs["pool_pre_ping"] = POSTGRES_POOL_PRE_PING
                final_engine_kwargs["pool_recycle"] = POSTGRES_POOL_RECYCLE

                # any passed in kwargs override the defaults
                final_engine_kwargs.update(extra_engine_kwargs)

            logger.info(f"Creating engine with kwargs: {final_engine_kwargs}")
            # echo=True here for inspecting all emitted db queries
            engine = create_engine(connection_string, **final_engine_kwargs)

            if use_iam:
                event.listen(engine, "do_connect", provide_iam_token)

            cls._engine = engine

    @classmethod
    def get_engine(cls) -> Engine:
        if not cls._engine:
            raise RuntimeError("Engine not initialized. Must call init_engine first.")
        return cls._engine

    @classmethod
    def set_app_name(cls, app_name: str) -> None:
        cls._app_name = app_name

    @classmethod
    def get_app_name(cls) -> str:
        if not cls._app_name:
            return ""
        return cls._app_name

    @classmethod
    def reset_engine(cls) -> None:
        with cls._lock:
            if cls._engine:
                cls._engine.dispose()
                cls._engine = None


def get_all_tenant_ids() -> list[str]:
    """Returning [None] means the only tenant is the 'public' or self hosted tenant."""

    tenant_ids: list[str]

    if not MULTI_TENANT:
        return [POSTGRES_DEFAULT_SCHEMA]

    with get_session_with_shared_schema() as session:
        result = session.execute(
            text(
                f"""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', '{POSTGRES_DEFAULT_SCHEMA}')"""
            )
        )
        tenant_ids = [row[0] for row in result]

    valid_tenants = [
        tenant
        for tenant in tenant_ids
        if tenant is None or tenant.startswith(TENANT_ID_PREFIX)
    ]
    return valid_tenants


def get_sqlalchemy_engine() -> Engine:
    return SqlEngine.get_engine()


async def get_async_connection() -> Any:
    """
    Custom connection function for async engine when using IAM auth.
    """
    host = POSTGRES_HOST
    port = POSTGRES_PORT
    user = POSTGRES_USER
    db = POSTGRES_DB
    token = get_iam_auth_token(host, port, user, AWS_REGION_NAME)

    # asyncpg requires 'ssl="require"' if SSL needed
    return await asyncpg.connect(
        user=user, password=token, host=host, port=int(port), database=db, ssl="require"
    )


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

        if USE_IAM_AUTH:

            @event.listens_for(_ASYNC_ENGINE.sync_engine, "do_connect")
            def provide_iam_token_async(
                dialect: Any, conn_rec: Any, cargs: Any, cparams: Any
            ) -> None:
                # For async engine using asyncpg, we still need to set the IAM token here.
                host = POSTGRES_HOST
                port = POSTGRES_PORT
                user = POSTGRES_USER
                token = get_iam_auth_token(host, port, user, AWS_REGION_NAME)
                cparams["password"] = token
                cparams["ssl"] = ssl_context

    return _ASYNC_ENGINE


engine = get_sqlalchemy_async_engine()
AsyncSessionLocal = sessionmaker(  # type: ignore
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@contextmanager
def get_session_with_current_tenant() -> Generator[Session, None, None]:
    tenant_id = get_current_tenant_id()

    with get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


# Used in multi tenant mode when need to refer to the shared `public` schema
@contextmanager
def get_session_with_shared_schema() -> Generator[Session, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as session:
        yield session
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _set_search_path_on_checkout__listener(
    dbapi_conn: Any, connection_record: Any, connection_proxy: Any
) -> None:
    """Listener to make sure we ALWAYS set the search path on checkout."""
    tenant_id = get_current_tenant_id()
    if tenant_id and is_valid_schema_name(tenant_id):
        with dbapi_conn.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{tenant_id}"')


@contextmanager
def get_session_with_tenant(*, tenant_id: str) -> Generator[Session, None, None]:
    """
    Generate a database session for a specific tenant.
    """
    engine = get_sqlalchemy_engine()

    event.listen(engine, "checkout", _set_search_path_on_checkout__listener)

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
        except Exception:
            raise RuntimeError(f"search_path not set for {tenant_id}")
        finally:
            cursor.close()

        try:
            # automatically rollback or close
            with Session(bind=connection, expire_on_commit=False) as session:
                yield session
        finally:
            # always reset the search path on exit
            if MULTI_TENANT:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute('SET search_path TO "$user", public')
                finally:
                    cursor.close()


def get_session() -> Generator[Session, None, None]:
    """For use w/ Depends for FastAPI endpoints.

    Has some additional validation, and likely should be merged
    with get_session_context_manager in the future."""
    tenant_id = get_current_tenant_id()
    if tenant_id == POSTGRES_DEFAULT_SCHEMA and MULTI_TENANT:
        raise BasicAuthenticationError(detail="User must authenticate")

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    with get_session_context_manager() as db_session:
        yield db_session


@contextlib.contextmanager
def get_session_context_manager() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    tenant_id = get_current_tenant_id()
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


def _set_search_path_on_transaction__listener(
    session: Session, transaction: Any, connection: Any, *args: Any, **kwargs: Any
) -> None:
    """Every time a new transaction is started,
    set the search_path from the session's info."""
    tenant_id = session.info.get("tenant_id")
    if tenant_id:
        connection.exec_driver_sql(f'SET search_path = "{tenant_id}"')


async def get_async_session(
    tenant_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """For use w/ Depends for *async* FastAPI endpoints.

    For standard `async with ... as ...` use, use get_async_session_context_manager.
    """

    if tenant_id is None:
        tenant_id = get_current_tenant_id()

    engine = get_sqlalchemy_async_engine()

    async with AsyncSession(engine, expire_on_commit=False) as async_session:
        # set the search path on sync session as well to be extra safe
        event.listen(
            async_session.sync_session,
            "after_begin",
            _set_search_path_on_transaction__listener,
        )

        if POSTGRES_IDLE_SESSIONS_TIMEOUT:
            await async_session.execute(
                text(
                    f"SET idle_in_transaction_session_timeout = {POSTGRES_IDLE_SESSIONS_TIMEOUT}"
                )
            )

        if not is_valid_schema_name(tenant_id):
            raise HTTPException(status_code=400, detail="Invalid tenant ID")

        # don't need to set the search path for self-hosted + default schema
        # this is also true for sync sessions, but just not adding it there for
        # now to simplify / not change too much
        if MULTI_TENANT or tenant_id != POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
            await async_session.execute(text(f'SET search_path = "{tenant_id}"'))

        yield async_session


def get_async_session_context_manager(
    tenant_id: str | None = None,
) -> AsyncContextManager[AsyncSession]:
    return asynccontextmanager(get_async_session)(tenant_id)


async def warm_up_connections(
    sync_connections_to_warm_up: int = 20, async_connections_to_warm_up: int = 20
) -> None:
    sync_postgres_engine = get_sqlalchemy_engine()
    connections = [
        sync_postgres_engine.connect() for _ in range(sync_connections_to_warm_up)
    ]
    for conn in connections:
        conn.execute(text("SELECT 1"))
    for conn in connections:
        conn.close()

    async_postgres_engine = get_sqlalchemy_async_engine()
    async_connections = [
        await async_postgres_engine.connect()
        for _ in range(async_connections_to_warm_up)
    ]
    for async_conn in async_connections:
        await async_conn.execute(text("SELECT 1"))
    for async_conn in async_connections:
        await async_conn.close()


def provide_iam_token(dialect: Any, conn_rec: Any, cargs: Any, cparams: Any) -> None:
    if USE_IAM_AUTH:
        host = POSTGRES_HOST
        port = POSTGRES_PORT
        user = POSTGRES_USER
        region = os.getenv("AWS_REGION_NAME", "us-east-2")
        # Configure for psycopg2 with IAM token
        configure_psycopg2_iam_auth(cparams, host, port, user, region)
