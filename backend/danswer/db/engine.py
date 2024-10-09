import contextlib
import contextvars
import re
import threading
import time
from collections.abc import AsyncGenerator
from collections.abc import Generator
from datetime import datetime
from typing import Any
from typing import ContextManager

import jwt
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from sqlalchemy import event
from sqlalchemy import text
from sqlalchemy.engine import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from danswer.configs.app_configs import LOG_POSTGRES_CONN_COUNTS
from danswer.configs.app_configs import LOG_POSTGRES_LATENCY
from danswer.configs.app_configs import MULTI_TENANT
from danswer.configs.app_configs import POSTGRES_API_SERVER_POOL_OVERFLOW
from danswer.configs.app_configs import POSTGRES_API_SERVER_POOL_SIZE
from danswer.configs.app_configs import POSTGRES_DB
from danswer.configs.app_configs import POSTGRES_HOST
from danswer.configs.app_configs import POSTGRES_PASSWORD
from danswer.configs.app_configs import POSTGRES_POOL_PRE_PING
from danswer.configs.app_configs import POSTGRES_POOL_RECYCLE
from danswer.configs.app_configs import POSTGRES_PORT
from danswer.configs.app_configs import POSTGRES_USER
from danswer.configs.app_configs import SECRET_JWT_KEY
from danswer.configs.constants import POSTGRES_DEFAULT_SCHEMA
from danswer.configs.constants import POSTGRES_UNKNOWN_APP_NAME
from danswer.utils.logger import setup_logger


logger = setup_logger()

SYNC_DB_API = "psycopg2"
ASYNC_DB_API = "asyncpg"

# global so we don't create more than one engine per process
# outside of being best practice, this is needed so we can properly pool
# connections and not create a new pool on every request

_ASYNC_ENGINE: AsyncEngine | None = None
SessionFactory: sessionmaker[Session] | None = None

if LOG_POSTGRES_LATENCY:
    # Function to log before query execution
    @event.listens_for(Engine, "before_cursor_execute")
    def before_cursor_execute(  # type: ignore
        conn, cursor, statement, parameters, context, executemany
    ):
        conn.info["query_start_time"] = time.time()

    # Function to log after query execution
    @event.listens_for(Engine, "after_cursor_execute")
    def after_cursor_execute(  # type: ignore
        conn, cursor, statement, parameters, context, executemany
    ):
        total_time = time.time() - conn.info["query_start_time"]
        # don't spam TOO hard
        if total_time > 0.1:
            logger.debug(
                f"Query Complete: {statement}\n\nTotal Time: {total_time:.4f} seconds"
            )


if LOG_POSTGRES_CONN_COUNTS:
    # Global counter for connection checkouts and checkins
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


"""END DEBUGGING LOGGING"""


def get_db_current_time(db_session: Session) -> datetime:
    """Get the current time from Postgres representing the start of the transaction
    Within the same transaction this value will not update
    This datetime object returned should be timezone aware, default Postgres timezone is UTC
    """
    result = db_session.execute(text("SELECT NOW()")).scalar()
    if result is None:
        raise ValueError("Database did not return a time")
    return result


# Regular expression to validate schema names to prevent SQL injection
SCHEMA_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


def is_valid_schema_name(name: str) -> bool:
    return SCHEMA_NAME_REGEX.match(name) is not None


class SqlEngine:
    """Class to manage a global SQLAlchemy engine (needed for proper resource control).
    Will eventually subsume most of the standalone functions in this file.
    Sync only for now.
    """

    _engine: Engine | None = None
    _lock: threading.Lock = threading.Lock()
    _app_name: str = POSTGRES_UNKNOWN_APP_NAME

    # Default parameters for engine creation
    DEFAULT_ENGINE_KWARGS = {
        "pool_size": 20,
        "max_overflow": 5,
        "pool_pre_ping": POSTGRES_POOL_PRE_PING,
        "pool_recycle": POSTGRES_POOL_RECYCLE,
    }

    def __init__(self) -> None:
        pass

    @classmethod
    def _init_engine(cls, **engine_kwargs: Any) -> Engine:
        """Private helper method to create and return an Engine."""
        connection_string = build_connection_string(
            db_api=SYNC_DB_API, app_name=cls._app_name + "_sync"
        )
        merged_kwargs = {**cls.DEFAULT_ENGINE_KWARGS, **engine_kwargs}
        return create_engine(connection_string, **merged_kwargs)

    @classmethod
    def init_engine(cls, **engine_kwargs: Any) -> None:
        """Allow the caller to init the engine with extra params. Different clients
        such as the API server and different Celery workers and tasks
        need different settings.
        """
        with cls._lock:
            if not cls._engine:
                cls._engine = cls._init_engine(**engine_kwargs)

    @classmethod
    def get_engine(cls) -> Engine:
        """Gets the SQLAlchemy engine. Will init a default engine if init hasn't
        already been called. You probably want to init first!
        """
        if not cls._engine:
            with cls._lock:
                if not cls._engine:
                    cls._engine = cls._init_engine()
        return cls._engine

    @classmethod
    def set_app_name(cls, app_name: str) -> None:
        """Class method to set the app name."""
        cls._app_name = app_name

    @classmethod
    def get_app_name(cls) -> str:
        """Class method to get current app name."""
        if not cls._app_name:
            return ""
        return cls._app_name


def build_connection_string(
    *,
    db_api: str = ASYNC_DB_API,
    user: str = POSTGRES_USER,
    password: str = POSTGRES_PASSWORD,
    host: str = POSTGRES_HOST,
    port: str = POSTGRES_PORT,
    db: str = POSTGRES_DB,
    app_name: str | None = None,
) -> str:
    if app_name:
        return f"postgresql+{db_api}://{user}:{password}@{host}:{port}/{db}?application_name={app_name}"
    return f"postgresql+{db_api}://{user}:{password}@{host}:{port}/{db}"


def get_sqlalchemy_engine() -> Engine:
    return SqlEngine.get_engine()


def get_sqlalchemy_async_engine() -> AsyncEngine:
    global _ASYNC_ENGINE
    if _ASYNC_ENGINE is None:
        # Underlying asyncpg cannot accept application_name directly in the connection string
        # https://github.com/MagicStack/asyncpg/issues/798
        connection_string = build_connection_string()
        _ASYNC_ENGINE = create_async_engine(
            connection_string,
            connect_args={
                "server_settings": {
                    "application_name": SqlEngine.get_app_name() + "_async"
                }
            },
            # async engine is only used by API server, so we can use those values
            # here as well
            pool_size=POSTGRES_API_SERVER_POOL_SIZE,
            max_overflow=POSTGRES_API_SERVER_POOL_OVERFLOW,
            pool_pre_ping=POSTGRES_POOL_PRE_PING,
            pool_recycle=POSTGRES_POOL_RECYCLE,
        )
    return _ASYNC_ENGINE


# Context variable to store the current tenant ID
# This allows us to maintain tenant-specific context throughout the request lifecycle
# The default value is set to POSTGRES_DEFAULT_SCHEMA for non-multi-tenant setups
# This context variable works in both synchronous and asynchronous contexts
# In async code, it's automatically carried across coroutines
# In sync code, it's managed per thread
current_tenant_id = contextvars.ContextVar(
    "current_tenant_id", default=POSTGRES_DEFAULT_SCHEMA
)


# Dependency to get the current tenant ID and set the context variable
def get_current_tenant_id(request: Request) -> str:
    """Dependency that extracts the tenant ID from the JWT token in the request and sets the context variable."""
    if not MULTI_TENANT:
        tenant_id = POSTGRES_DEFAULT_SCHEMA
        current_tenant_id.set(tenant_id)
        return tenant_id

    token = request.cookies.get("tenant_details")
    if not token:
        # If no token is present, use the default schema or handle accordingly
        tenant_id = POSTGRES_DEFAULT_SCHEMA
        current_tenant_id.set(tenant_id)
        return tenant_id

    try:
        payload = jwt.decode(token, SECRET_JWT_KEY, algorithms=["HS256"])
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            raise HTTPException(
                status_code=400, detail="Invalid token: tenant_id missing"
            )
        if not is_valid_schema_name(tenant_id):
            raise ValueError("Invalid tenant ID format")
        current_tenant_id.set(tenant_id)
        return tenant_id
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token format")
    except ValueError as e:
        # Let the 400 error bubble up
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Internal server error")


def get_session_with_tenant(tenant_id: str | None = None) -> Session:
    if tenant_id is None:
        tenant_id = current_tenant_id.get()

    if not is_valid_schema_name(tenant_id):
        logger.error(f"Invalid tenant ID: {tenant_id}")
        raise Exception("Invalid tenant ID")

    engine = SqlEngine.get_engine()
    session = Session(engine, expire_on_commit=False)

    @event.listens_for(session, "after_begin")
    def set_search_path(session: Session, transaction: Any, connection: Any) -> None:
        connection.execute(text("SET search_path TO :schema"), {"schema": tenant_id})

    return session


def get_session(
    tenant_id: str = Depends(get_current_tenant_id),
) -> Generator[Session, None, None]:
    """Generate a database session with the appropriate tenant schema set."""
    engine = get_sqlalchemy_engine()
    with Session(engine, expire_on_commit=False) as session:
        if MULTI_TENANT:
            if not is_valid_schema_name(tenant_id):
                raise HTTPException(status_code=400, detail="Invalid tenant ID")
            # Set the search_path to the tenant's schema
            session.execute(text(f'SET search_path = "{tenant_id}"'))
        yield session


async def get_async_session(
    tenant_id: str = Depends(get_current_tenant_id),
) -> AsyncGenerator[AsyncSession, None]:
    """Generate an async database session with the appropriate tenant schema set."""
    engine = get_sqlalchemy_async_engine()
    async with AsyncSession(engine, expire_on_commit=False) as async_session:
        if MULTI_TENANT:
            if not is_valid_schema_name(tenant_id):
                raise HTTPException(status_code=400, detail="Invalid tenant ID")
            # Set the search_path to the tenant's schema
            await async_session.execute(text(f'SET search_path = "{tenant_id}"'))
        yield async_session


def get_session_context_manager() -> ContextManager[Session]:
    """Context manager for database sessions."""
    return contextlib.contextmanager(get_session)()


def get_session_factory() -> sessionmaker[Session]:
    """Get a session factory."""
    global SessionFactory
    if SessionFactory is None:
        SessionFactory = sessionmaker(bind=get_sqlalchemy_engine())
    return SessionFactory


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
