import contextlib
import time
from collections.abc import AsyncGenerator
from collections.abc import Generator
from datetime import datetime
from typing import ContextManager

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
from danswer.configs.app_configs import POSTGRES_DB
from danswer.configs.app_configs import POSTGRES_HOST
from danswer.configs.app_configs import POSTGRES_PASSWORD
from danswer.configs.app_configs import POSTGRES_POOL_PRE_PING
from danswer.configs.app_configs import POSTGRES_POOL_RECYCLE
from danswer.configs.app_configs import POSTGRES_PORT
from danswer.configs.app_configs import POSTGRES_USER
from danswer.configs.constants import POSTGRES_UNKNOWN_APP_NAME
from danswer.utils.logger import setup_logger

logger = setup_logger()

SYNC_DB_API = "psycopg2"
ASYNC_DB_API = "asyncpg"

POSTGRES_APP_NAME = (
    POSTGRES_UNKNOWN_APP_NAME  # helps to diagnose open connections in postgres
)

# global so we don't create more than one engine per process
# outside of being best practice, this is needed so we can properly pool
# connections and not create a new pool on every request
_SYNC_ENGINE: Engine | None = None
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


def init_sqlalchemy_engine(app_name: str) -> None:
    global POSTGRES_APP_NAME
    POSTGRES_APP_NAME = app_name


def get_sqlalchemy_engine() -> Engine:
    global _SYNC_ENGINE
    if _SYNC_ENGINE is None:
        connection_string = build_connection_string(
            db_api=SYNC_DB_API, app_name=POSTGRES_APP_NAME + "_sync"
        )
        _SYNC_ENGINE = create_engine(
            connection_string,
            pool_size=40,
            max_overflow=10,
            pool_pre_ping=POSTGRES_POOL_PRE_PING,
            pool_recycle=POSTGRES_POOL_RECYCLE,
        )
    return _SYNC_ENGINE


def get_sqlalchemy_async_engine() -> AsyncEngine:
    global _ASYNC_ENGINE
    if _ASYNC_ENGINE is None:
        # underlying asyncpg cannot accept application_name directly in the connection string
        # https://github.com/MagicStack/asyncpg/issues/798
        connection_string = build_connection_string()
        _ASYNC_ENGINE = create_async_engine(
            connection_string,
            connect_args={
                "server_settings": {"application_name": POSTGRES_APP_NAME + "_async"}
            },
            pool_size=40,
            max_overflow=10,
            pool_pre_ping=POSTGRES_POOL_PRE_PING,
            pool_recycle=POSTGRES_POOL_RECYCLE,
        )
    return _ASYNC_ENGINE


def get_session_context_manager() -> ContextManager[Session]:
    return contextlib.contextmanager(get_session)()


def get_session() -> Generator[Session, None, None]:
    # The line below was added to monitor the latency caused by Postgres connections
    # during API calls.
    # with tracer.trace("db.get_session"):
    with Session(get_sqlalchemy_engine(), expire_on_commit=False) as session:
        yield session


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(
        get_sqlalchemy_async_engine(), expire_on_commit=False
    ) as async_session:
        yield async_session


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


def get_session_factory() -> sessionmaker[Session]:
    global SessionFactory
    if SessionFactory is None:
        SessionFactory = sessionmaker(bind=get_sqlalchemy_engine())
    return SessionFactory
