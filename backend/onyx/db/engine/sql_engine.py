import os
import re
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy import pool
from sqlalchemy.engine import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DB_READONLY_PASSWORD
from onyx.configs.app_configs import DB_READONLY_USER
from onyx.configs.app_configs import LOG_POSTGRES_CONN_COUNTS
from onyx.configs.app_configs import LOG_POSTGRES_LATENCY
from onyx.configs.app_configs import POSTGRES_DB
from onyx.configs.app_configs import POSTGRES_HOST
from onyx.configs.app_configs import POSTGRES_PASSWORD
from onyx.configs.app_configs import POSTGRES_POOL_PRE_PING
from onyx.configs.app_configs import POSTGRES_POOL_RECYCLE
from onyx.configs.app_configs import POSTGRES_PORT
from onyx.configs.app_configs import POSTGRES_USE_NULL_POOL
from onyx.configs.app_configs import POSTGRES_USER
from onyx.configs.constants import POSTGRES_UNKNOWN_APP_NAME
from onyx.db.engine.iam_auth import provide_iam_token
from onyx.server.utils import BasicAuthenticationError
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from shared_configs.contextvars import get_current_tenant_id

# Moved is_valid_schema_name here to avoid circular import


logger = setup_logger()


# Schema name validation (moved here to avoid circular import)
SCHEMA_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def is_valid_schema_name(name: str) -> bool:
    return SCHEMA_NAME_REGEX.match(name) is not None


SYNC_DB_API = "psycopg2"
ASYNC_DB_API = "asyncpg"

# why isn't this in configs?
USE_IAM_AUTH = os.getenv("USE_IAM_AUTH", "False").lower() == "true"


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


class SqlEngine:
    _engine: Engine | None = None
    _readonly_engine: Engine | None = None
    _lock: threading.Lock = threading.Lock()
    _readonly_lock: threading.Lock = threading.Lock()
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
    def init_readonly_engine(
        cls,
        pool_size: int,
        # is really `pool_max_overflow`, but calling it `max_overflow` to stay consistent with SQLAlchemy
        max_overflow: int,
        **extra_engine_kwargs: Any,
    ) -> None:
        """NOTE: enforce that pool_size and pool_max_overflow are passed in. These are
        important args, and if incorrectly specified, we have run into hitting the pool
        limit / using too many connections and overwhelming the database."""
        with cls._readonly_lock:
            if cls._readonly_engine:
                return

            if not DB_READONLY_USER or not DB_READONLY_PASSWORD:
                raise ValueError(
                    "Custom database user credentials not configured in environment variables"
                )

            # Build connection string with custom user
            connection_string = build_connection_string(
                user=DB_READONLY_USER,
                password=DB_READONLY_PASSWORD,
                use_iam_auth=False,  # Custom users typically don't use IAM auth
                db_api=SYNC_DB_API,  # Explicitly use sync DB API
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

            if USE_IAM_AUTH:
                event.listen(engine, "do_connect", provide_iam_token)

            cls._readonly_engine = engine

    @classmethod
    def get_engine(cls) -> Engine:
        if not cls._engine:
            raise RuntimeError("Engine not initialized. Must call init_engine first.")
        return cls._engine

    @classmethod
    def get_readonly_engine(cls) -> Engine:
        if not cls._readonly_engine:
            raise RuntimeError(
                "Readonly engine not initialized. Must call init_readonly_engine first."
            )
        return cls._readonly_engine

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


def get_sqlalchemy_engine() -> Engine:
    return SqlEngine.get_engine()


def get_readonly_sqlalchemy_engine() -> Engine:
    return SqlEngine.get_readonly_engine()


@contextmanager
def get_session_with_current_tenant() -> Generator[Session, None, None]:
    """Standard way to get a DB session."""
    tenant_id = get_current_tenant_id()
    with get_session_with_tenant(tenant_id=tenant_id) as session:
        yield session


@contextmanager
def get_session_with_current_tenant_if_none(
    session: Session | None,
) -> Generator[Session, None, None]:
    if session is None:
        tenant_id = get_current_tenant_id()
        with get_session_with_tenant(tenant_id=tenant_id) as session:
            yield session
    else:
        yield session


# Used in multi tenant mode when need to refer to the shared `public` schema
@contextmanager
def get_session_with_shared_schema() -> Generator[Session, None, None]:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA)
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as session:
        yield session
    CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


@contextmanager
def get_session_with_tenant(*, tenant_id: str) -> Generator[Session, None, None]:
    """
    Generate a database session for a specific tenant.
    """
    engine = get_sqlalchemy_engine()

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    # no need to use the schema translation map for self-hosted + default schema
    if not MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
        with Session(bind=engine, expire_on_commit=False) as session:
            yield session
        return

    # Create connection with schema translation to handle querying the right schema
    schema_translate_map = {None: tenant_id}
    with engine.connect().execution_options(
        schema_translate_map=schema_translate_map
    ) as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            yield session


def get_session() -> Generator[Session, None, None]:
    """For use w/ Depends for FastAPI endpoints.

    Has some additional validation, and likely should be merged
    with get_session_with_current_tenant in the future."""
    tenant_id = get_current_tenant_id()
    if tenant_id == POSTGRES_DEFAULT_SCHEMA and MULTI_TENANT:
        raise BasicAuthenticationError(detail="User must authenticate")

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    with get_session_with_current_tenant() as db_session:
        yield db_session


@contextmanager
def get_db_readonly_user_session_with_current_tenant() -> (
    Generator[Session, None, None]
):
    """
    Generate a database session using a custom database user for the current tenant.
    The custom user credentials are obtained from environment variables.
    """
    tenant_id = get_current_tenant_id()

    readonly_engine = get_readonly_sqlalchemy_engine()

    if not is_valid_schema_name(tenant_id):
        raise HTTPException(status_code=400, detail="Invalid tenant ID")

    # no need to use the schema translation map for self-hosted + default schema
    if not MULTI_TENANT and tenant_id == POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE:
        with Session(readonly_engine, expire_on_commit=False) as session:
            yield session
        return

    schema_translate_map = {None: tenant_id}
    with readonly_engine.connect().execution_options(
        schema_translate_map=schema_translate_map
    ) as connection:
        with Session(bind=connection, expire_on_commit=False) as session:
            yield session
